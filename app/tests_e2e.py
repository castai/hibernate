import logging
import sys
import time
from main import handle_suspend, handle_resume, get_cloud_provider, cluster_id, castai_api_token
from cast_utils import get_cluster_status, get_castai_nodes, get_castai_policy
from utils import step

logger = logging.getLogger()
logger.setLevel(level=logging.INFO)
handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)


class Scenario:
    def __init__(self, cluster_id, castai_api_token):
        self.cluster_id = cluster_id
        self.castai_api_token = castai_api_token
        self.cloud = get_cloud_provider(cluster_id=self.cluster_id, castai_api_token=self.castai_api_token)

    @step
    def cluster_is_ready(self):
        cluster = get_cluster_status(self.cluster_id, self.castai_api_token)
        logging.info(f"TEST cluster status: {cluster.get('status')}, id: {cluster.get('id')}")
        assert cluster.get('status') == 'ready', "Cluster is not ready"

    @step
    def get_cloud(self):
        logging.info(f'Cloud detect: {self.cloud}')
        assert self.cloud in ('EKS', 'GKE', 'AKS'), f"Unexpected cloud: {self.cloud}"

    @step
    def suspend(self):
        logging.info(f"TEST suspending cluster")
        handle_suspend(self.cloud)

        time.sleep(300)  # sometimes delete nodes takes longer time
        nodes = get_castai_nodes(self.cluster_id, self.castai_api_token)
        logging.info(f'Number of nodes found in the cluster: {len(nodes["items"])}')
        assert len(nodes["items"]) == 1, "Incorrect number of nodes after suspend"

    def double_suspend(self):
        logging.info(f"TEST suspending already suspended cluster")
        handle_suspend(self.cloud)

        time.sleep(30) # make sure nodes are not about to be added
        current_policies = get_castai_policy(self.cluster_id, self.castai_api_token)
        nodes = get_castai_nodes(self.cluster_id, self.castai_api_token)
        logging.info(f'Number of nodes found in the cluster: {len(nodes["items"])}')
        assert len(nodes["items"]) == 1 and not current_policies["enabled"], "Incorrect number of nodes after suspend"

    @step
    def resume(self):
        logging.info(f"TEST resuming cluster")
        handle_resume()
        current_policies = get_castai_policy(self.cluster_id, self.castai_api_token)
        assert current_policies["enabled"], "Policy not enabled after resume"


def test_all():
    logging.info("TEST test started")
    scenario = Scenario(cluster_id, castai_api_token)
    scenario.cluster_is_ready()
    scenario.get_cloud()
    # scenario.suspend()
    # time.sleep(15)
    # scenario.double_suspend()
    # scenario.cluster_is_ready()
    time.sleep(15)
    scenario.resume()
    scenario.cluster_is_ready()
    logging.info("TEST test finished")
