import logging
import sys
import time
from app import main
from cast_utils import get_cluster_status
from utils import basic_retry, step

logger = logging.getLogger()
logger.setLevel(level=logging.INFO)
handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)


class Scenario:
    @step
    @basic_retry(attempts=2, pause=5)
    def cluster_is_ready(self):
        cluster = get_cluster_status(main.cluster_id, main.castai_api_token)
        logging.info(f"TEST cluster status: {cluster.get('status')}, id: {cluster.get('id')}")
        assert cluster.get('status') == 'ready'


    @step
    def suspend(self):
        logging.info(f"TEST suspending cluster")
        main.handle_suspend()

        time.sleep(180)
        nodes = main.get_castai_nodes(main.cluster_id, main.castai_api_token)
        logging.info(f'Number of nodes found in the cluster: {len(nodes["items"])}')
        assert len(nodes["items"])==1


    @step
    def resume(self):
        logging.info(f"TEST resuming cluster")
        main.handle_resume()
        policy_json = main.get_castai_policy(main.cluster_id, main.castai_api_token)
        assert policy_json["enabled"]


def test_all():
    logging.info("TEST test started")
    scenario = Scenario()
    scenario.cluster_is_ready()
    scenario.suspend()
    time.sleep(15)
    scenario.cluster_is_ready()
    time.sleep(15)
    scenario.resume()
    scenario.cluster_is_ready()
