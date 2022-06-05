#   Copyright 2022 James Andariese
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.

.PHONY: all always-build

RELPATH := $(shell realpath .)

all: version.txt
always-build: proto/api_info_pb2.py proto/api_v1alpha1_pb2.py proto/api_info_pb2_grpc.py proto/api_v1alpha1_pb2_grpc.py

dist-clean:
	rm -rf proto

clean:
	rm -f proto/api_{info,v1alpha1}_pb2{,_grpc}.py

proto:
	mkdir -p proto

proto/api_info.proto: | proto
	curl -o $@ https://raw.githubusercontent.com/kubevirt/kubevirt/main/pkg/hooks/info/api_info.proto

proto/api_v1alpha1.proto: | proto
	curl -o $@ https://raw.githubusercontent.com/kubevirt/kubevirt/main/pkg/hooks/v1alpha1/api_v1alpha1.proto

proto/api_info_pb2_grpc.py: proto/api_info.proto
	python -m grpc_tools.protoc --python_out=./proto --grpc_python_out=./proto -I ./proto api_info.proto
	sed -e 's/^\(import api_.*_pb2 as api__.*__pb2\)$$/from . \1/' < $@ > $@.tmp
	mv $@.tmp $@

proto/api_v1alpha1_pb2_grpc.py: proto/api_v1alpha1.proto
	python -m grpc_tools.protoc --python_out=proto --grpc_python_out=proto -I proto api_v1alpha1.proto
	sed -e 's/^\(import api_.*_pb2 as api__.*__pb2\)$$/from . \1/' < $@ > $@.tmp
	mv $@.tmp $@

proto/api_info_pb2.py: proto/api_info_pb2_grpc.py
proto/api_v1alpha1_pb2.py: proto/api_v1alpha1_pb2_grpc.py

version.txt: version.txt.tmpl always-build
	gomplate < version.txt.tmpl > version.txt
	git add version.txt

dev: always-build
	bash devbuild.sh

prepare-release: version.txt

test:
	echo "Add tests" 1>&2
	false
