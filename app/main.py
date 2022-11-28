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

my_node_name = os.environ.get("MY_NODE_NAME")
logging.basicConfig(format="%(asctime)s %(message)s", level=logging.INFO)

castai_pause_toleration = "scheduling.cast.ai/paused-cluster"
spot_fallback = "scheduling.cast.ai/spot-fallback"
cast_nodeID_label = "provisioner.cast.ai/node-id"
cast_namespace = "castai-agent"
cast_webhook_namespace = "castai-pod-node-lifecycle"
kube_system_namespace = "kube-system"

# TODO: check essential pods CPU/RAM requirements and pick big enough node
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
    policy_changed = toggle_unschedulable_pod_policy_enabled(cluster_id, castai_api_token, True)
    if not policy_changed:
        raise Exception("could not enable CAST AI autoscaler.")

    logging.info("Resume operation completed.")


def handle_suspend():
    toggle_unschedulable_pod_policy_enabled(cluster_id, castai_api_token, False)
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
    else:
        raise Exception("no ready hibernation node exist")

    add_special_tolerations(client=k8s_v1_apps, namespace=kube_system_namespace, toleration=castai_pause_toleration)
    add_special_tolerations(client=k8s_v1_apps, namespace=cast_namespace, toleration=castai_pause_toleration)
    add_special_tolerations(client=k8s_v1_apps, namespace=cast_webhook_namespace, toleration=castai_pause_toleration)

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
