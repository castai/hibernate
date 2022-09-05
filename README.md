# Hibernator shrinks and expands your cluster on schedule

This utility currently is on best effort support by @Leon Kuperman and @Augustinas Stirbis through community slack

Run this command to install Hibernator CronJobs
```shell
kubectl apply -f https://raw.githubusercontent.com/castai/hibernator/initial_branch/deploy.yaml
```

Create API token with Full Access permissions and encode base64
```shell
echo "98349587234524jh523452435kj2h4k5h2k34j5h2kj34h5k23h5k2345jhk2" | base64
```

use this value to update Secret
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: castai-hibernator
  namespace: castai-agent
type: Opaque
data:
  API_KEY: >-
    API-key-REPLACE-ME-WITH-ABOVE...==
```
 

## How it works

hibernator-pause Job will 
 - Disable Unscheduled Pod Policy (to prevent growing cluster)
 - Prepare Hibernation node (node that will stay hosting essential components)
 - Mark essential Deployments with Hibernation toleration
 - Delete all other nodes (only hibernation node should stay running)

hibernator-resume Job will
 - Renable Unscheduled Pod Policy to allow cluster to expand to needed size

## TODO
 - Adjust AKS system node size if too big
 - Auto detect Cloud 
