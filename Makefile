all::	clean build
build::	protobuf dist
dist::	dist-cli dist-executor
clean::	clean-py clean-proto clean-dist

DOT := \033[34m●\033[39m
TICK := \033[32m✔\033[39m

clean-py:
	@echo "$(DOT) Deleting python compiled files."
	find ./ddocker -name "*.py[co]" -exec rm {} \;
	@echo "$(TICK) Deleting python compiled files."

clean-proto:
	@echo "$(DOT) Deleting python proto modules."
	rm -rf ./ddocker/proto
	@echo "$(TICK) Deleting python proto modules."

clean-dist:
	@echo "$(DOT) Deleting distribution files."
	rm -rf ./dist build ddocker.egg-info
	@echo "$(TICK) Deleting distribution files."

protobuf: clean-proto
	@echo "$(DOT) Building python proto modules."
	protoc ./proto/*.proto --python_out=./ddocker/
	touch ./ddocker/proto/__init__.py
	@echo "$(TICK) Building python proto modules."

dist-cli: protobuf
	@echo "$(DOT) Building ddocker distribution binary."
	./pants ddocker:cli
	@echo "$(TICK) Building ddocker distribution binary."

dist-executor: protobuf
	@echo "$(DOT) Building ddocker executor."
	./pants ddocker:executor
	@echo "$(TICK) Building ddocker executor."
