import os
import logging
from cast_utils import *
from k8s_utils import *
from kubernetes import client, config


castai_api_token = os.environ["API_KEY"]
cluster_id = os.environ["CLUSTER_ID"]
cloud = os.environ["CLOUD"]
action = os.environ["ACTION"]
logging.basicConfig(format="%(asctime)s %(message)s", level=logging.DEBUG)

castai_pause_toleration="scheduling.cast.ai/paused-cluster"
azure_system_node_label = "kubernetes.azure.com/mode=system"
cast_nodeID_label = "provisioner.cast.ai/node-id"
cast_namespace = "castai-agent"
kube_system_namespace = "kube-system"

# TODO: check essentail pods CPU/RAM requirements and pick big enough node
instance_type = {
    "GKE":"e2-standard-2",
    "EKS":"m5a.large",
    "AKS": "Standard_F2s_v2"
}


config.load_incluster_config()
k8s_v1 = client.CoreV1Api()
k8s_v1_apps = client.AppsV1Api()


if __name__ == '__main__':
    logging.info("Hibernation input parameters token: %s, clusterId: %s, cloud: %s, action: %s",
                 castai_api_token, cluster_id, cloud, action)

    if action == "resume":
        logging.info("Resuming cluster, autoscaling will be enabled")
        policy_changed = set_unschedulable_pod_policy_enabled(cluster_id, castai_api_token, True)
        exit(0)

    policy_changed = set_unschedulable_pod_policy_enabled(cluster_id, castai_api_token, False)
    hibernation_node_id = hibernation_node_already_exist(client=k8s_v1, taint=castai_pause_toleration, k8s_label=None)
    if cloud == "AKS":
        hibernation_node_id = hibernation_node_already_exist(client=k8s_v1, taint=castai_pause_toleration, k8s_label=azure_system_node_label)

    if not hibernation_node_id:
        logging.info("No hibernation node found, should make one")
        if cloud in ['GCP', 'EKS']:
            logging.info("Cloud: %s", cloud)
            cordon_all_nodes(k8s_v1, exclude_node_id=None)
            hibernation_node_id = create_hibernation_node(cluster_id, castai_api_token,
                                                   instance_type=instance_type[cloud], k8s_taint=castai_pause_toleration)
        else:
            logging.info("Cloud: AKS")
            hibernation_node_id = azure_system_node(k8s_v1, k8s_label=azure_system_node_label, taint=castai_pause_toleration)
            cordon_all_nodes(k8s_v1, exclude_node_id=hibernation_node_id)

    if hibernation_node_id:
        logging.info("Hibernation node: %s", hibernation_node_id)
    else:
        exit(-1)

    # add_special_tolerations(client=k8s_v1_apps, namespace=kube_system_namespace, toleration=castai_pause_toleration)
    add_special_tolerations(client=k8s_v1_apps, namespace=cast_namespace, toleration=castai_pause_toleration)

    delete_all_pausable_nodes(cluster_id, castai_api_token, hibernation_node_id)

    logging.info("Pause operation completed.")
