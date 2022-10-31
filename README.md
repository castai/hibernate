# Hibernate shrinks and expands your cluster on schedule

This utility currently is on best effort support by @Leon Kuperman and @Augustinas Stirbis through community slack

Run this command to install Hibernate CronJobs
```shell
kubectl apply -f https://raw.githubusercontent.com/castai/hibernate/main/deploy.yaml
```

Create API token with Full Access permissions and encode base64
```shell
echo -n "98349587234524jh523452435kj2h4k5h2k34j5h2kj34h5k23h5k2345jhk2" | base64
```

use this value to update Secret
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: castai-Hibernate
  namespace: castai-agent
type: Opaque
data:
  API_KEY: >-
    CASTAI-API-KEY-REPLACE-ME-WITH-ABOVE==
```
 
for convenience one liner
```shell
kubectl get secret castai-hibernate -n castai-agent -o json | jq --arg API_KEY "$(echo -n 9834958-CASTAI-API-KEY-REPLACE-ME-5k2345jhk2 | base64)" '.data["API_KEY"]=$API_KEY' | kubectl apply -f -
```

## How it works

Hibernate-pause Job will 
 - Disable Unscheduled Pod Policy (to prevent growing cluster)
 - Prepare Hibernation node (node that will stay hosting essential components)
 - Mark essential Deployments with Hibernation toleration
 - Delete all other nodes (only hibernation node should stay running)

Hibernate-resume Job will
 - Renable Unscheduled Pod Policy to allow cluster to expand to needed size

Override default hibernate-node size
 - Set the HIBERNATE_NODE environment variable to override the default node sizing selections. Make sure the size selected is appropriate for your cloud. 

## TODO
 - Auto detect Cloud 

