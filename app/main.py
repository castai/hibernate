import logging
import os
from cast_utils import *
from k8s_utils import *
from kubernetes import client, config
from dotenv import load_dotenv
from pathlib import Path

local_development = os.environ.get("LOCAL_DEVELOPMENT")
# local_development = True

if not local_development:
    # Run hibernate from container inside k8s
    config.load_incluster_config()
else:
    # Run hibernate from local IDE
    logging.info(f"local dev: {local_development}")
    load_dotenv(dotenv_path=Path('../.env'))
    config.load_kube_config()

k8s_v1 = client.CoreV1Api()
k8s_v1_apps = client.AppsV1Api()

castai_api_token = os.environ["API_KEY"]
cluster_id = os.environ["CLUSTER_ID"]
hibernate_node_type_override = os.environ.get("HIBERNATE_NODE")
cloud = os.environ["CLOUD"]
action = os.environ["ACTION"]
user_namespaces_to_keep = os.environ.get("NAMESPACES_TO_KEEP")
protect_removal_disabled = os.environ.get("PROTECT_REMOVAL_DISABLED")

my_node_name = os.environ.get("MY_NODE_NAME")
logging.basicConfig(format="%(asctime)s %(message)s", level=logging.INFO)

castai_pause_toleration = "scheduling.cast.ai/paused-cluster"
spot_fallback = "scheduling.cast.ai/spot-fallback"
cast_nodeID_label = "provisioner.cast.ai/node-id"
namespaces_to_keep = [
    "castai-pod-node-lifecycle",
    "kube-system"
]

# TODO: not all instances types are available in all regions
instance_type = {
    "GKE": "e2-standard-2",
    "EKS": "m5a.large",
    "AKS": "Standard_D2as_v5"
}

cloud_labels = {
    "GKE": None,
    "EKS": None,
    "AKS": "kubernetes.azure.com/mode=system"
}


def handle_resume():
    logging.info("Resuming cluster, autoscaling will be enabled")
    policy_changed = toggle_autoscaler_top_flag(cluster_id, castai_api_token, True)
    if not policy_changed:
        raise Exception("could not enable CAST AI autoscaler.")

    logging.info("Resume operation completed.")


def handle_suspend():
    current_policies = get_castai_policy(cluster_id, castai_api_token)
    if current_policies["enabled"] == False:
        logging.info("Cluster is already with disabled autoscaler policies, reverting to resume.")
        handle_resume()
        return

    toggle_autoscaler_top_flag(cluster_id, castai_api_token, False)

    my_node_name_id = ""
    if my_node_name:
        logging.info("Job pod node name found: %s", my_node_name)
        my_node_name_id = get_node_castai_id(client=k8s_v1, node_name=my_node_name)

    if hibernate_node_type_override:
        hibernate_node_type = hibernate_node_type_override
    else:
        hibernate_node_type = instance_type[cloud]

    candidate_node = get_suitable_hibernation_node(cluster_id=cluster_id, castai_api_token=castai_api_token,
                                                   instance_type=hibernate_node_type, cloud=cloud)

    hibernation_node_id = None
    if candidate_node:
        logging.info("Found suitable hibernation candidate node: %s", candidate_node)
        add_node_taint(client=k8s_v1, pause_taint=castai_pause_toleration, node_name=candidate_node)
        hibernation_node_id = check_hibernation_node_readiness(client=k8s_v1, taint=castai_pause_toleration,
                                                               node_name=candidate_node)

    if my_node_name_id == hibernation_node_id:
        node_list_result = get_castai_nodes(cluster_id, castai_api_token)
        nodes = []
        for node in node_list_result["items"]:
            if node["state"]["phase"] == "ready":
                nodes.append(node)
        logging.info(f'Number of READY nodes found in the cluster: {len(nodes)}')
        if len(nodes) == 1:
            logging.info("Hibernation node is the same as job pod node, pause job just ran, exiting")
            return 0

    if not hibernation_node_id:
        logging.info("No suitable hibernation node found, should make one")
        hibernation_node_id = create_hibernation_node(cluster_id, castai_api_token, instance_type=hibernate_node_type,
                                                      k8s_taint=castai_pause_toleration, cloud=cloud)

    if not hibernation_node_id:
        raise Exception("could not create hibernation node")

    node_name = get_castai_node_name_by_id(cluster_id, castai_api_token, hibernation_node_id)

    hibernation_node_status = check_hibernation_node_readiness(client=k8s_v1, taint=castai_pause_toleration,
                                                               node_name=node_name)
    if hibernation_node_status:
        logging.info("Hibernation node exist: %s", hibernation_node_id)
        cordon_all_nodes(k8s_v1, protect_removal_disabled, exclude_node_id=hibernation_node_id)
        time.sleep(20)
    else:
        raise Exception("no ready hibernation node exist")

    for deploy in get_deployments_names_with_system_priority_class(client=k8s_v1_apps):
        add_special_toleration(client=k8s_v1_apps, deployment=deploy, toleration=castai_pause_toleration)

    if user_namespaces_to_keep:
        logging.info(f'user provided namespaces_to_keep is not empty {user_namespaces_to_keep}')
        for namespace in user_namespaces_to_keep.split(","):
            namespaces_to_keep.append(namespace)

    for namespace in namespaces_to_keep:
        logging.info(f"additional namespace {namespace} to patch")
        deploys = k8s_v1_apps.list_namespaced_deployment(namespace=namespace)
        for deploy in deploys.items:
            logging.info(f'Additional {namespace} deployment {deploy.metadata.name} will be patched')
            add_special_toleration(client=k8s_v1_apps, deployment=deploy, toleration=castai_pause_toleration)
    time.sleep(30)  # allow core dns and other critical pods to be scheduled on hibernation node

    defer_job_node_deletion = False

    if my_node_name_id and my_node_name_id != hibernation_node_id:
        logging.info("Job pod node id and hibernation node is not the same")
        delete_all_pausable_nodes(cluster_id=cluster_id, castai_api_token=castai_api_token,
                                  hibernation_node_id=hibernation_node_id,
                                  protect_removal_disabled=protect_removal_disabled, job_node_id=my_node_name_id)
        defer_job_node_deletion = True
    else:
        logging.info("Delete all nodes except hibernation node")
        delete_all_pausable_nodes(cluster_id, castai_api_token, hibernation_node_id, protect_removal_disabled)

    remove_node_taint(client=k8s_v1, pause_taint=castai_pause_toleration, node_id=hibernation_node_id)

    if defer_job_node_deletion:
        logging.info("Delete jobs node with id %s:", my_node_name_id)
        delete_all_pausable_nodes(cluster_id=cluster_id, castai_api_token=castai_api_token,
                                  hibernation_node_id=hibernation_node_id,
                                  protect_removal_disabled=protect_removal_disabled)

    logging.info("Pause operation completed.")


def main():
    logging.info("Hibernation input parameters token: %s, clusterId: %s, cloud: %s, action: %s",
                 castai_api_token, cluster_id, cloud, action)

    if action == "resume":
        return handle_resume()

    try:
        handle_suspend()
    except:
        logging.info("Hibernation failed, resuming cluster")
        handle_resume()


if __name__ == '__main__':
    try:
        main()
    except Exception as err:
        logging.error("action failed:" + str(err))
        exit(1)
