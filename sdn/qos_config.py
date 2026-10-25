"""
Shared loader for config/config.yaml.

Used by three different interpreters, so it only depends on PyYAML and
the standard library:
- sdn/topology.py and sdn/run_experiment.py (system python3 under sudo)
- sdn/controller.py (Ryu, project .venv)
- backend/ (Flask, project .venv)
"""
import os

import yaml

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
DEFAULT_CONFIG = os.path.join(PROJECT_ROOT, 'config', 'config.yaml')


class ConfigError(Exception):
    pass


def load_config(path=None):
    """Load and sanity-check the config. Raises ConfigError on bad values."""
    path = path or os.environ.get('SDN_QOS_CONFIG', DEFAULT_CONFIG)
    with open(path) as f:
        cfg = yaml.safe_load(f)
    cfg['_path'] = os.path.abspath(path)
    _validate(cfg)
    return cfg


def _validate(cfg):
    topo = cfg['topology']
    switches = topo['switches']
    hosts = topo['hosts']
    for h, info in hosts.items():
        if info['switch'] not in switches:
            raise ConfigError('host %s is on unknown switch %s' % (h, info['switch']))
    for link in topo['links']:
        for end in ('a', 'b'):
            if link[end] not in switches:
                raise ConfigError('link uses unknown switch %s' % link[end])
    for name, path in topo['paths'].items():
        for a, b in zip(path, path[1:]):
            if link_ports(cfg, a, b) is None:
                raise ConfigError('path %s uses %s-%s, which is not a link' % (name, a, b))
    if topo['primary_path'] not in topo['paths']:
        raise ConfigError('primary_path %s is not defined' % topo['primary_path'])
    for role in ('server', 'client'):
        if cfg['video'][role] not in hosts:
            raise ConfigError('video %s %s is not a host' % (role, cfg['video'][role]))
    q = cfg['queues']
    for link in topo['links']:
        cap = link_capacity_mbps(cfg, link)
        if q['video_min_mbps'] + q['default_min_mbps'] > cap:
            raise ConfigError('queue minimum rates add up to more than the %s Mbit/s '
                              'capacity of %s-%s' % (cap, link['a'], link['b']))
    th = cfg['monitoring']['utilization_threshold']
    if not 0 < th <= 1:
        raise ConfigError('utilization_threshold must be between 0 and 1')


def link_capacity_mbps(cfg, link):
    return link.get('capacity_mbps', cfg['links']['default_capacity_mbps'])


def link_ports(cfg, a, b):
    """Return (port on a, port on b) for the configured link a-b, or None."""
    for link in cfg['topology']['links']:
        if link['a'] == a and link['b'] == b:
            return link['a_port'], link['b_port']
        if link['a'] == b and link['b'] == a:
            return link['b_port'], link['a_port']
    return None


def dpid_of(cfg, switch):
    return cfg['topology']['switches'][switch]


def switch_of_dpid(cfg, dpid):
    for name, d in cfg['topology']['switches'].items():
        if d == dpid:
            return name
    return None


def host_by_ip(cfg, ip):
    for name, info in cfg['topology']['hosts'].items():
        if info['ip'] == ip:
            return name
    return None
