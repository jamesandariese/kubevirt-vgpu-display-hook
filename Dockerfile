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

FROM python:3-alpine

RUN mkdir -p /app/kubevirt/pkg/hooks/info /app/kubevirt/pkg/hooks/v1alpha1 /app/kubevirt/pkg/hooks/v1alpha2

WORKDIR /app
ADD requirements.txt /app
RUN pip install -r requirements.txt

ENTRYPOINT ["python3", "/app/server.py"]

ADD . /app

RUN find . ; python -m doctest server.py