#!/usr/bin/env python3
"""检查目标 Service/Pod CIDR 与服务器本地 IPv4 范围是否重叠。"""

from __future__ import annotations

import argparse
import ipaddress
import sys
from typing import Sequence


class ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValueError(message)


def parser() -> ArgumentParser:
    result = ArgumentParser(add_help=True)
    result.add_argument('--service-cidr', required=True)
    result.add_argument('--pod-cidr', required=True)
    result.add_argument('--address', action='append', default=[])
    result.add_argument('--route', action='append', default=[])
    return result


def network(value: str) -> ipaddress.IPv4Network:
    parsed = ipaddress.ip_network(value, strict=False)
    if not isinstance(parsed, ipaddress.IPv4Network):
        raise ValueError(f'not IPv4: {value}')
    return parsed


def address_network(value: str) -> ipaddress.IPv4Network:
    parsed = ipaddress.ip_interface(value)
    if not isinstance(parsed, ipaddress.IPv4Interface):
        raise ValueError(f'not IPv4: {value}')
    return ipaddress.ip_network(f'{parsed.ip}/32')


def stop(reason: str) -> int:
    print('RESULT=STOP_CIDR_OVERLAP')
    print(f'REASON={reason}')
    return 10


def main(arguments: Sequence[str] | None = None) -> int:
    try:
        options = parser().parse_args(arguments)
        service = network(options.service_cidr)
        pod = network(options.pod_cidr)
        addresses = [address_network(value) for value in options.address]
        routes = [network(value) for value in options.route]
    except (ValueError, ipaddress.AddressValueError, ipaddress.NetmaskValueError) as error:
        print('RESULT=STOP_CIDR_INVALID')
        print(f'REASON={error}')
        return 10

    if service.overlaps(pod):
        return stop('service-and-pod-overlap')
    for local in addresses:
        if service.overlaps(local):
            return stop('service-overlaps-local-address')
        if pod.overlaps(local):
            return stop('pod-overlaps-local-address')
    for local in routes:
        if service.overlaps(local):
            return stop('service-overlaps-local-route')
        if pod.overlaps(local):
            return stop('pod-overlaps-local-route')

    print('RESULT=PASS_CIDRS')
    print('REASON=no-server-local-overlap')
    print('SCOPE=SERVER_LOCAL_SCOPE_ONLY')
    return 0


if __name__ == '__main__':
    sys.exit(main())
