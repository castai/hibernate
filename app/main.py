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
hibernate_node_type = os.environ.get("HIBERNATE_NODE")
cloud = os.environ["CLOUD"]
action = os.environ["ACTION"]
user_namespaces_to_keep = os.environ.get("NAMESPACES_TO_KEEP")

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
    toggle_autoscaler_top_flag(cluster_id, castai_api_token, False)
    hibernation_node_id = hibernation_node_already_exist(client=k8s_v1, taint=castai_pause_toleration,
                                                         k8s_label=cloud_labels[cloud])

    if not hibernation_node_id and cloud == "AKS":
        logging.info("Checking special Azure case if suitable Azure node could be converted")
        hibernation_node_id = azure_system_node(k8s_v1, taint=castai_pause_toleration, k8s_label=cloud_labels[cloud])

    if not hibernation_node_id:
        logging.info("No hibernation node found, should make one")
        if hibernate_node_type:
            hibernate_node_size = hibernate_node_type
        else:
            hibernate_node_size = instance_type[cloud]
        hibernation_node_id = create_hibernation_node(cluster_id, castai_api_token, instance_type=hibernate_node_size,
                                                      k8s_taint=castai_pause_toleration, cloud=cloud)

    if hibernation_node_id:
        logging.info("Hibernation node exist: %s", hibernation_node_id)
        cordon_all_nodes(k8s_v1, exclude_node_id=hibernation_node_id)
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


    defer_job_node_deletion = False
    my_node_name_id = ""
    if my_node_name:
        logging.info("Job pod node name found: %s", my_node_name)
        my_node_name_id = get_node_castai_id(client=k8s_v1, node_name=my_node_name)

    if my_node_name_id and my_node_name_id != hibernation_node_id:
        logging.info("Job pod node id and hibernation node is not the same")
        delete_all_pausable_nodes(cluster_id, castai_api_token, hibernation_node_id, my_node_name_id)
        defer_job_node_deletion = True
    else:
        logging.info("Delete all nodes except hibernation node")
        delete_all_pausable_nodes(cluster_id, castai_api_token, hibernation_node_id)

    hibernation_node_name = get_castai_node_by_id(cluster_id=cluster_id, castai_api_token=castai_api_token,
                                                  node_id=hibernation_node_id)
    remove_node_taint(client=k8s_v1, pause_taint=castai_pause_toleration, node_name=hibernation_node_name)

    if defer_job_node_deletion:
        logging.info("Delete jobs node with id %s:", my_node_name_id)
        delete_castai_node(cluster_id, castai_api_token, my_node_name_id)

    logging.info("Pause operation completed.")


def main():
    logging.info("Hibernation input parameters token: %s, clusterId: %s, cloud: %s, action: %s",
                 castai_api_token, cluster_id, cloud, action)

    if action == "resume":
        return handle_resume()

    handle_suspend()


if __name__ == '__main__':
    try:
        main()
    except Exception as err:
        logging.error("action failed:" + str(err))
        exit(1)
