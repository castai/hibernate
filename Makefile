default: release

PLATFORMS = linux/amd64,linux/arm64
APP="castai/hibernate"
TAG_LATEST=$(APP):latest
TAG_VERSION=$(APP):v0.10

gke:
	(cd ./hack/gke && terraform init && terraform apply -auto-approve)

eks:
	(cd ./hack/eks && terraform init && terraform apply -target module.vpc -auto-approve && terraform apply -target module.eks -auto-approve && terraform apply -auto-approve)

aks:
	(cd ./hack/aks && terraform init && terraform apply -var-file=tf.vars -auto-approve)

kind:
	(cd ./hack/kind && sh run.sh)

pull:
	docker pull $(TAG_LATEST)

build:
	@echo "==> Building hibernate container"
	docker build --cache-from $(TAG_LATEST) --platform linux/amd64 -t $(TAG_LATEST) -t $(TAG_VERSION) .

multiarch:
	@echo "==> Building hibernate container"
	docker buildx create --use
	docker buildx build  --platform $(PLATFORMS)  -t $(TAG_VERSION)  -t $(TAG_LATEST) --push .

publish:
	@echo "==> pushing to docker hub"
	docker push --all-tags $(APP)

release: pull
release: build
release: publish

deploy:
	kubectl apply -f deploy.yaml
