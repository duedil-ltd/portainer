all::	build
build::	protobuf
setup:: protobuf env
clean::	clean-py clean-proto clean-dist clean-env

DOT := \033[34m●\033[39m
TICK := \033[32m✔\033[39m

clean-py:
	find ./portainer -name "*.py[co]" -exec rm {} \;

clean-proto:
	rm -rf ./portainer/proto/*_pb2.py

clean-dist:
	rm -rf ./dist

clean-env:
	rm -rf ./bin/env

protobuf: clean-proto
	@echo "$(DOT) Building python proto modules."
	protoc ./proto/*.proto --python_out=./portainer/
	@echo "$(TICK)  Building python proto modules."

env:
	@echo "$(DOT) Building virtual environment."
	bin/setup
	@echo "$(TICK)  Finished setting up virtual environment."

test:
	@echo "$(DOT) Running tests."
	bin/tests
	@echo "$(TICK)  Tests passed!"
