#!/bin/bash

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

U=`uuid`
docker build -t jamesandariese/matoes:$U . 
docker push jamesandariese/matoes:$U 
echo "docker.io/jamesandariese/matoes:$U" 
echo ':%s/docker[.]io[/]jamesandariese[/]matoes:[A-Fa-f0-9]\{8\}-[A-Fa-f0-9]\{4\}-[A-Fa-f0-9]\{4\}-[A-Fa-f0-9]\{4\}-[A-Fa-f0-9]\{12\}/docker.io\/jamesandariese\/matoes:'"$U"'/' | pbcopy
echo "you may also execute your clipboard in vim to replace the uuid"

