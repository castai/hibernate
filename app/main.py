import os
from cast_utils import *
from k8s_utils import *
from kubernetes import client, config

# Run hibernate from local IDE
# from dotenv import load_dotenv
# load_dotenv()
# config.load_kube_config()

# Run hibernate from container inside k8s
config.load_incluster_config()

castai_api_token = os.environ["API_KEY"]
cluster_id = os.environ["CLUSTER_ID"]
cloud = os.environ["CLOUD"]
action = os.environ["ACTION"]
logging.basicConfig(format="%(asctime)s %(message)s", level=logging.INFO)

castai_pause_toleration = "scheduling.cast.ai/paused-cluster"
spot_fallback = "scheduling.cast.ai/spot-fallback"
cast_nodeID_label = "provisioner.cast.ai/node-id"
cast_namespace = "castai-agent"
cast_webhook_namespace = "castai-pod-node-lifecycle"
kube_system_namespace = "kube-system"

# TODO: check essential pods CPU/RAM requirements and pick big enough node
instance_type = {
    "GKE": "e2-standard-2",
    "EKS": "m5a.large",
    "AKS": "Standard_F2s_v2"
}

cloud_labels = {
    "GKE": None,
    "EKS": None,
    "AKS": "kubernetes.azure.com/mode=system"
}

k8s_v1 = client.CoreV1Api()
k8s_v1_apps = client.AppsV1Api()

if __name__ == '__main__':
    logging.info("Hibernation input parameters token: %s, clusterId: %s, cloud: %s, action: %s",
                 castai_api_token, cluster_id, cloud, action)

    if action == "resume":
        logging.info("Resuming cluster, autoscaling will be enabled")
        policy_changed = toggle_unschedulable_pod_policy_enabled(cluster_id, castai_api_token, True)
        exit(0)

    policy_changed = toggle_unschedulable_pod_policy_enabled(cluster_id, castai_api_token, False)

    hibernation_node_id = hibernation_node_already_exist(client=k8s_v1, taint=castai_pause_toleration,
                                                             k8s_label=cloud_labels[cloud])
    if not hibernation_node_id and cloud == "AKS":
        logging.info("Checking special Azure case if suitable Azure node could be converted")
        hibernation_node_id = azure_system_node(k8s_v1, k8s_label=cloud_labels[cloud], taint=castai_pause_toleration)

    if not hibernation_node_id:
        logging.info("No hibernation node found, should make one")
        hibernation_node_id = create_hibernation_node(cluster_id, castai_api_token, instance_type=instance_type[cloud],
                                                          k8s_taint=castai_pause_toleration, cloud=cloud)

    if hibernation_node_id:
        logging.info("Hibernation node exist: %s", hibernation_node_id)
        cordon_all_nodes(k8s_v1, exclude_node_id=hibernation_node_id)
    else:
        logging.error("No ready hibernation node exist")
        exit(-1)

    add_special_tolerations(client=k8s_v1_apps, namespace=kube_system_namespace, toleration=castai_pause_toleration)
    add_special_tolerations(client=k8s_v1_apps, namespace=cast_namespace, toleration=castai_pause_toleration)
    add_special_tolerations(client=k8s_v1_apps, namespace=cast_webhook_namespace, toleration=castai_pause_toleration)

    delete_all_pausable_nodes(cluster_id, castai_api_token, hibernation_node_id)

    logging.info("Pause operation completed.")
