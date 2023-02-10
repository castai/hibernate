import logging
from utils import basic_retry
from kubernetes.client.rest import ApiException


class K8sAPIError(Exception):
    pass


def cordon_all_nodes(client, protect_eviction_disabled, exclude_node_id: str):
    """cordon all the nodes so essential components could be scheduled only on hybernation node"""
    logging.info("Cordon function")

    node_body = {
        "spec": {
            "unschedulable": True
        }
    }

    node_list = client.list_node()
    for node in node_list.items:
        logging.info("Inspecting node %s to cordon", node.metadata.name)
        skip=False
        if node.metadata.labels.get("autoscaling.cast.ai/removal-disabled")=="true" and protect_eviction_disabled=="true":
            skip=True
        if node.metadata.labels.get("provisioner.cast.ai/node-id") != exclude_node_id and not skip:
            logging.info("Cordoning: %s" % node.metadata.name)
            client.patch_node(node.metadata.name, node_body)
        else:
            logging.info("skip Cordoning node: %s" % node.metadata.name)


def deployment_tolerates(deployment, toleration):
    """" check if deployment tolerates a taint on a hibernation node"""
    if deployment.spec.template.spec.tolerations:
        if [tol_key for tol_key in deployment.spec.template.spec.tolerations if tol_key.key == toleration]:
            return True
    return False


@basic_retry(attempts=2, pause=5)
def add_special_toleration(client, deployment: str, toleration: str):
    """" modify essential deployment to keep them running on hibernation node (tolerate node)"""
    logging.info("add tolerations to essential workloads function")

    toleration_to_add = {
        'key': toleration,
        'effect': 'NoSchedule',
        'operator': 'Exists'
    }

    deployment_name = deployment.metadata.name
    if not deployment_tolerates(deployment, toleration):
        current_tolerations = deployment.spec.template.spec.tolerations
        logging.info("Patching and restarting: %s" % deployment_name)
        if current_tolerations is None:
            current_tolerations = []
        current_tolerations.append(toleration_to_add)

        restart_body = {
            'spec': {
                'template': {
                    'spec': {
                        'tolerations': current_tolerations
                    }
                }
            }
        }

        patch_result = None
        try:
            patch_result = client.patch_namespaced_deployment(deployment_name, deployment.metadata.namespace,
                                                              restart_body)
        except ApiException as e:
            raise K8sAPIError(
                f'Exception when calling patching deployment: {deployment_name} with result {patch_result}') from e

        if patch_result:
            logging.info("Patch complete...")
    else:
        logging.info(f'SKIP Deployment {deployment_name} already has toleration')


def hibernation_node_already_exist(client, taint: str, k8s_label: str):
    """" Node with hibernation taint already exist """
    node_list = client.list_node(label_selector=k8s_label)
    for node in node_list.items:
        if node.spec.taints and node_is_ready(node):
            for current_taint in node.spec.taints:
                if current_taint.to_dict()["key"] == taint:
                    logging.info("found hibernation compatible node with label %s and taint %s", k8s_label, taint)
                    return node.metadata.labels.get("provisioner.cast.ai/node-id")


def node_is_ready(node):
    node_scheduling = node.spec.unschedulable
    for condition in node.status.conditions:
        if condition.status and condition.type == "Ready" and not node_scheduling:
            return True
    return False


def azure_system_node(client, taint: str, k8s_label: str):
    """ mark existing AKS system node with hibernation Taint if small system node is found"""

    node_list = client.list_node(label_selector=k8s_label)
    hibernation_node = None

    if len(node_list.items) > 0:
        for node in node_list.items:
            if int(node.status.capacity["cpu"]) == 2 and node_is_ready(node):
                logging.info("Found Node with 2 CPU %s", node.metadata.name)
                hibernation_node = node
                break

    if hibernation_node:
        taint_to_add = {"key": taint, "effect": "NoSchedule"}
        logging.info("found single system nodes, will add taint")

        current_taints = hibernation_node.spec.taints
        if current_taints is None:
            current_taints = []
        current_taints.append(taint_to_add)

        taint_body = {
            "spec": {
                "taints": current_taints
            },
            "metadata": {
                "labels": {
                    "scheduling.cast.ai/paused-cluster": "true",
                    "scheduling.cast.ai/spot-fallback": "true",
                    "scheduling.cast.ai/spot": "true"
                }
            }
        }

        logging.info("patching node %s with taint", hibernation_node.metadata.name)
        patch_result = None
        try:
            patch_result = client.patch_node(hibernation_node.metadata.name, taint_body)
        except ApiException as e:
            raise K8sAPIError(f'Failed to taint node {hibernation_node.metadata.name}') from e

        if patch_result:
            logging.info("node %s successfully patched", hibernation_node.metadata.name)
            return hibernation_node.metadata.labels["provisioner.cast.ai/node-id"]


def remove_node_taint(client, pause_taint: str, node_name):
    """ remove specific taint from node"""
    logging.info(f'patching node {node_name} to remove {pause_taint} taint')

    k8s_label = "kubernetes.io/hostname=" + node_name
    node = client.list_node(label_selector=k8s_label).items[0]

    taints = node.spec.taints
    filtered_taints = list(filter(lambda x: x.key != pause_taint, taints))
    taint_body = {"spec": {"taints": filtered_taints}}

    try:
        patch_result = client.patch_node(node.metadata.name, taint_body)
    except ApiException as e:
        raise K8sAPIError(f'Failed to remove taint from node {node.metadata.name}') from e

    if patch_result:
        logging.info(f'node {node_name} successfully patched')
        return True
    else:
        logging.error(f'failed to patch node {node_name}, with details {patch_result}')


def get_node_castai_id(client, node_name: str):
    """" Node with hibernation taint already exist """
    k8s_label = "kubernetes.io/hostname=" + node_name
    node_list = client.list_node(label_selector=k8s_label)
    if len(node_list.items) == 1:
        for node in node_list.items:
            node_id = node.metadata.labels.get("provisioner.cast.ai/node-id")
            logging.info("found Node %s with id %s that is running Pause Job ", node.metadata.name, node_id)
            return node_id


def get_deployments_names_with_system_priority_class(client):
    """Return all system-critical priority-class deployments"""
    deployments = client.list_deployment_for_all_namespaces()
    critical_deploys = []
    for deployment in deployments.items:
        if has_system_priority_class(deployment): critical_deploys.append(deployment)
    return critical_deploys


def has_system_priority_class(deployment):
    """ validate if Deployment is system critical"""
    if deployment.spec.template.spec.priority_class_name in ("system-cluster-critical","system-node-critical"):
        logging.info(f'SYSTEM CRITICAL {deployment.metadata.name} found')
        return True
    else:
        return False
