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

import concurrent.futures
import json
import re
import sys
import uuid
import xml.etree.ElementTree as ET
import difflib

import grpc

import proto.api_info_pb2 as info_proto
import proto.api_info_pb2_grpc as info_grpc
import proto.api_v1alpha1_pb2 as v1alpha1_proto
import proto.api_v1alpha1_pb2_grpc as v1alpha1_grpc


XMLNS_QEMU="{http://libvirt.org/schemas/domain/qemu/1.0}"
XMLNS_KUBEVIRT="{http://kubevirt.io}"
ET.register_namespace('qemu', XMLNS_QEMU.strip('{}'))
ET.register_namespace('kubevirt', XMLNS_KUBEVIRT.strip('{}'))


def _ensure_commandline(domain):
    """
    ensure a qemu:commandline is present in domain

    >>> ET.tostring(_ensure_commandline(ET.fromstring('<domain />')))
    b'<domain xmlns:qemu="http://libvirt.org/schemas/domain/qemu/1.0"><qemu:commandline /></domain>'
    """
    commandline = domain.find(XMLNS_QEMU+"commandline")

    if not commandline:
        commandline = domain.makeelement(XMLNS_QEMU+"commandline", {})
        domain.append(commandline)
    return domain


def awesome_hex(sucky_hex, force_width=None, match_re=re.compile(r'^(0[xX])?(?P<hex>[0-9a-fA-F]*)([hH])?$')):
    """
    this is a hex "parser" that was designed for human input.  it assumes
    dumb inputs are possible but will try its best.  but if you give it
    sucky_hex, it can only do its best to make it awesome_hex.

    remove leading '0's
    remove leading 'x's
        (or 'X's, 'cause AOL invented caps lock and now we're stuck with it)
        this only happens if the string started with 0x (or if it was horribly mangled)
    remove leading '0's again
        if there was never a 0x, this second removal of 0s will be a noop
    also remove any trailing hex indicators ('h' or 'H')

    if all of these are specified at the same time.......... it will be fine?

    >>> awesome_hex("0xf", 4)
    '000f'

    >>> awesome_hex("0x00fh")
    '00f'
    """

    m = match_re.match(sucky_hex)
    if not m:
        raise ValueError(f'"{sucky_hex}" is not valid hex')
    x = m['hex']
    if x == '':
        return '0'
    better_int = int(x, 16)

    return "%0*x"%(force_width or len(x), better_int)


def _inject_qemu_commandline_for_pci_id_map(domain, alias_name, new_pci_id):
    """
    injects qemu commandline args in libvirt xml to override a pci device based on alias name or *

    >>> ET.tostring(_inject_qemu_commandline_for_pci_id_map(ET.fromstring("<domain/>"), "hostdev0", "0xfefe:bebeh"))
    b'<domain xmlns:qemu="http://libvirt.org/schemas/domain/qemu/1.0"><qemu:commandline><qemu:arg value="-set" /><qemu:arg value="device.hostdev0.x-pci-vendor-id=0xfefe" /><qemu:arg value="-set" /><qemu:arg value="device.hostdev0.x-pci-device-id=0xbebe" /></qemu:commandline></domain>'

    >>> ET.tostring(_inject_qemu_commandline_for_pci_id_map(ET.fromstring("<domain/>"), "hostdev0", "0xfebe:bebehhhh"))
    Traceback (most recent call last):
     ...
    ValueError: "bebehhhh" is not valid hex

    >>> ET.tostring(_inject_qemu_commandline_for_pci_id_map(ET.fromstring("<domain/>"), "hostdev0", "0xffff:1fh:bebe"))
    b'<domain xmlns:qemu="http://libvirt.org/schemas/domain/qemu/1.0"><qemu:commandline><qemu:arg value="-set" /><qemu:arg value="device.hostdev0.x-pci-vendor-id=0xffff" /><qemu:arg value="-set" /><qemu:arg value="device.hostdev0.x-pci-device-id=0x001f" /><qemu:arg value="-set" /><qemu:arg value="device.hostdev0.x-pci-sub-vendor-id=0xffff" /><qemu:arg value="-set" /><qemu:arg value="device.hostdev0.x-pci-sub-device-id=0xbebe" /></qemu:commandline></domain>'

    >>> ET.tostring(_inject_qemu_commandline_for_pci_id_map(ET.fromstring("<domain/>"), "hostdev0", "0xffff:1fh:febe:bebe"))
    b'<domain xmlns:qemu="http://libvirt.org/schemas/domain/qemu/1.0"><qemu:commandline><qemu:arg value="-set" /><qemu:arg value="device.hostdev0.x-pci-vendor-id=0xffff" /><qemu:arg value="-set" /><qemu:arg value="device.hostdev0.x-pci-device-id=0x001f" /><qemu:arg value="-set" /><qemu:arg value="device.hostdev0.x-pci-sub-vendor-id=0xfebe" /><qemu:arg value="-set" /><qemu:arg value="device.hostdev0.x-pci-sub-device-id=0xbebe" /></qemu:commandline></domain>'
    """
    _ensure_commandline(domain)
    commandline = domain.find(f"./{XMLNS_QEMU}commandline")

    pci_v = None
    pci_d = None
    pci_sv = None
    pci_sd = None

    pci_ids = ["0x"+awesome_hex(x, force_width=4) for x in new_pci_id.split(':')]
    if len(pci_ids) == 2:
        pci_v, pci_d = pci_ids
    elif len(pci_ids) == 3:
        pci_v, pci_d, pci_sd = pci_ids
        pci_sv = pci_v
    elif len(pci_ids) == 4:
        pci_v, pci_d, pci_sv, pci_sd = pci_ids
    else:
        raise ValueError(f"pci_id must be 2, 3, or 4 elements separated by ':', not {len(pci_ids)}")

    def cliappend(*args):
        for arg in args:
            commandline.append(commandline.makeelement(XMLNS_QEMU+"arg", {'value': arg}))

    if pci_v: cliappend('-set', f'device.{alias_name}.x-pci-vendor-id={pci_v}')
    if pci_d: cliappend('-set', f'device.{alias_name}.x-pci-device-id={pci_d}')
    if pci_sv: cliappend('-set', f'device.{alias_name}.x-pci-sub-vendor-id={pci_sv}')
    if pci_sd: cliappend('-set', f'device.{alias_name}.x-pci-sub-device-id={pci_sd}')

    return domain


def _get_vmi_pci_id_map(vmi, annotation_match_re=re.compile(r'^gpu-pci-id\.kubevirt\.exa\.fi(/(?P<alias>[^/]*))$')):
    pci_id_map = {}
    annotations = vmi.get('metadata', {}).get('annotations', {})
    for ann, newid in annotations.items():
        m = annotation_match_re.match(ann)
        if m:
            # if we've matched an annotation, it either has an alias or nothing.  nothing means "*"
            name = m['alias'] or '*'
            pci_id_map[name] = newid
    return pci_id_map

def ns_canonicalize(x):
    if isinstance(x, bytes):
        x = x.decode('utf-8')
    tree = ET.fromstring(x)
    ET.indent(tree)
    return ET.tostring(tree, encoding='utf-8').decode('utf-8')

def _ensure_alias(hostdev, index):
    alias = hostdev.find("./alias")
    if alias is not None:
        alias_name = alias.attrib['name']
    else:
        alias_name = f"hostdev{index}"
        hostdev.append(hostdev.makeelement('alias', {'name': alias_name}))
    return alias, alias_name


def _do_on_define_domain(vmibytes, domxml):
    """
    garbage in, garbage out
    >>> _do_on_define_domain(b'{}', b'<domain><garbage    /></domain>')
    b'<domain><garbage /></domain>'

    pci mappings work based on the alias which will automatically be added if necessary
    >>> _do_on_define_domain(b'{"metadata":{"annotations":{"gpu-pci-id.kubevirt.exa.fi/hostdev1":"febe:bebe"}}}', b'<domain><devices><hostdev /><hostdev display="on" /></devices></domain>')
    b'<domain xmlns:qemu="http://libvirt.org/schemas/domain/qemu/1.0"><devices><hostdev /><hostdev display="on"><alias name="hostdev1" /></hostdev></devices><qemu:commandline><qemu:arg value="-set" /><qemu:arg value="device.hostdev1.x-pci-vendor-id=0xfebe" /><qemu:arg value="-set" /><qemu:arg value="device.hostdev1.x-pci-device-id=0xbebe" /></qemu:commandline></domain>'

    wildcard mappings also work
    >>> _do_on_define_domain(b'{"metadata":{"annotations":{"gpu-pci-id.kubevirt.exa.fi":"febe:bebe"}}}', b'<domain><garbage    /></domain>')
    b'<domain><garbage /></domain>'

    ignore undefined pci mappings
    >>> _do_on_define_domain(b'{"metadata":{"annotations":{"gpu-pci-id.kubevirt.exa.fi/hostdev0":"febe:bebe"}}}', b'<domain><devices><hostdev /><hostdev display="on" /></devices></domain>')
    b'<domain><devices><hostdev /><hostdev display="on"><alias name="hostdev1" /></hostdev></devices></domain>'

    check the project folder for these
    >>> print(chr(10).join(difflib.unified_diff( ns_canonicalize(open('testvmi-expected.xml', 'rb').read()).split(chr(10)), ns_canonicalize(_do_on_define_domain(open('testvmi.json','rb').read(), open('testvmi.xml','rb').read()).decode('utf-8')).split(chr(10)), tofile='GENERATED', fromfile='testvmi-expected.xml')))
    <BLANKLINE>
    """

    vmi = json.loads(vmibytes.decode('utf-8'))
    pci_id_map = _get_vmi_pci_id_map(vmi)

    domain = ET.fromstring(domxml.decode('utf-8'))
    hostdev_index = 0
    for hostdev in domain.findall("./devices/hostdev"):
        if hostdev.attrib.get('display') == 'on':
            alias, alias_name = _ensure_alias(hostdev, hostdev_index)

            new_pci_id = pci_id_map.get(alias_name, pci_id_map.get('*'))
            if new_pci_id:
                _inject_qemu_commandline_for_pci_id_map(domain, alias_name, new_pci_id)

            video_model = domain.find("./devices/video/model")
            if video_model is not None:
                video_model.attrib['type'] = 'none'
        hostdev_index += 1
    newdom = ET.tostring(domain, 'utf-8')
    sys.stdout.flush()
    return newdom


class CallbacksServicer(v1alpha1_grpc.CallbacksServicer):
    def OnDefineDomain(self, request, context):
        print("--------\nSTART\n--------")
        print("--------\nVMI\n--------")
        print(request.vmi)
        print("--------\nDOMAIN\n--------")
        print(request.domainXML)
        print("--------\nPROCESSING\n--------")
        newdom = _do_on_define_domain(request.vmi, request.domainXML)
        print("--------\nNEWDOM\n--------")
        print(newdom)
        print("--------\nEND\n--------")
        return v1alpha1_proto.OnDefineDomainResult(domainXML=newdom)

class InfoServicer(info_grpc.InfoServicer):
    def Info(self, request, context):
        print("hello")
        return info_proto.InfoResult(versions=["v1alpha1"], name="datStuff", hookPoints=[info_proto.HookPoint(name="OnDefineDomain")])

def serve(address):
    server = grpc.server(concurrent.futures.ThreadPoolExecutor(max_workers=10))
    info_grpc.add_InfoServicer_to_server(InfoServicer(), server)
    v1alpha1_grpc.add_CallbacksServicer_to_server(CallbacksServicer(), server)

    print(server.add_insecure_port(address))
    print(server.add_insecure_port("unix:///var/run/kubevirt-hooks/domsniff.sock"))
    server.start()
    server.wait_for_termination()

if __name__ == "__main__":
    serve("[::]:4040")
