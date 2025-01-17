# -*- coding: utf_8 -*-
"""Dynamic Analyzer Operations."""
import json
import logging
import os
import random
import re
import subprocess
import threading
from pathlib import Path

from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.http import require_http_methods

from mobsf.DynamicAnalyzer.views.android.environment import (
    Environment,
)
from mobsf.MobSF.utils import (
    get_adb,
    get_device,
    is_md5,
    is_number,
)
from mobsf.StaticAnalyzer.models import StaticAnalyzerAndroid

logger = logging.getLogger(__name__)


# Helpers

def get_package_name(checksum):
    """Get Package Name from DB or Device."""
    try:
        static_android_db = StaticAnalyzerAndroid.objects.get(
            MD5=checksum)
        return static_android_db.PACKAGE_NAME
    except Exception:
        pkg_file = Path(settings.DWD_DIR) / 'packages.json'
        if not pkg_file.exists():
            return None
        with pkg_file.open(encoding='utf-8') as src:
            packages = json.load(src)
        if packages.get(checksum):
            return packages[checksum][0]
        return None


def send_response(data, api=False):
    """Return JSON Response."""
    if api:
        return data
    return HttpResponse(json.dumps(data),
                        content_type='application/json')


def is_attack_pattern(user_input):
    """Check for attacks."""
    atk_pattern = re.compile(r';|\$\(|\|\||&&')
    stat = re.findall(atk_pattern, user_input)
    if stat:
        logger.error('Possible RCE attack detected')
    return stat


def strict_package_check(user_input):
    """Strict package name check."""
    pat = re.compile(r'^\w+\.*[\w\.\$]+$')
    resp = re.match(pat, user_input)
    if not resp:
        logger.error('Invalid package/class name')
    return resp


def is_path_traversal(user_input):
    """Check for path traversal."""
    if (('../' in user_input)
        or ('%2e%2e' in user_input)
        or ('..' in user_input)
            or ('%252e' in user_input)):
        logger.error('Path traversal attack detected')
        return True
    return False


def invalid_params(api=False):
    """Standard response for invalid params."""
    msg = 'Invalid Parameters'
    logger.error(msg)
    data = {'status': 'failed', 'message': msg}
    if api:
        return data
    return send_response(data)

# AJAX


@require_http_methods(['POST'])
def mobsfy(request, api=False):
    """Configure Instance for Dynamic Analysis."""
    logger.info('MobSFying Android instance')
    data = {}
    try:
        identifier = request.POST['identifier']
        create_env = Environment(identifier)
        if not create_env.connect_n_mount():
            msg = 'Connection failed'
            data = {'status': 'failed', 'message': msg}
            return send_response(data, api)
        version = create_env.mobsfy_init()
        if not version:
            msg = 'Connection failed'
            data = {'status': 'failed', 'message': msg}
            return send_response(data, api)
        else:
            data = {'status': 'ok', 'android_version': version}
    except Exception as exp:
        logger.exception('MobSFying Android instance failed')
        data = {'status': 'failed', 'message': str(exp)}
    return send_response(data, api)

# AJAX


@require_http_methods(['POST'])
def execute_adb(request, api=False):
    """Execute ADB Commands."""
    data = {'status': 'ok', 'message': ''}
    cmd = request.POST['cmd']
    if cmd:
        args = [get_adb(),
                '-s',
                get_device()]
        try:
            proc = subprocess.Popen(args + cmd.split(' '),
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE)
            stdout, stderr = proc.communicate()
        except Exception:
            logger.exception('Executing ADB Commands')
        if stdout or stderr:
            out = stdout or stderr
            out = out.decode('utf8', 'ignore')
        else:
            out = ''
        data = {'status': 'ok', 'message': out}
    return send_response(data, api)

# AJAX


@require_http_methods(['POST'])
def get_component(request):
    """Get Android Component."""
    data = {}
    try:
        env = Environment()
        comp = request.POST['component']
        bin_hash = request.POST['hash']
        if is_attack_pattern(comp) or not is_md5(bin_hash):
            return invalid_params()
        comp = env.android_component(bin_hash, comp)
        data = {'status': 'ok', 'message': comp}
    except Exception as exp:
        logger.exception('Getting Android Component')
        data = {'status': 'failed', 'message': str(exp)}
    return send_response(data)

# AJAX


@require_http_methods(['POST'])
def take_screenshot(request, api=False):
    """Take Screenshot."""
    logger.info('Taking screenshot')
    data = {}
    try:
        env = Environment()
        bin_hash = request.POST['hash']
        if not is_md5(bin_hash):
            return invalid_params(api)
        data = {}
        rand_int = random.randint(1, 1000000)
        screen_dir = os.path.join(settings.UPLD_DIR,
                                  bin_hash + '/screenshots-apk/')
        if not os.path.exists(screen_dir):
            os.makedirs(screen_dir)
        outile = '{}screenshot-{}.png'.format(
            screen_dir,
            str(rand_int))
        env.screen_shot(outile)
        logger.info('Screenshot captured')
        data = {'status': 'ok'}
    except Exception as exp:
        logger.exception('Taking screenshot')
        data = {'status': 'failed', 'message': str(exp)}
    return send_response(data, api)
# AJAX


@require_http_methods(['POST'])
def screen_cast(request):
    """ScreenCast."""
    data = {}
    try:
        env = Environment()
        trd = threading.Thread(target=env.screen_stream)
        trd.daemon = True
        trd.start()
        data = {'status': 'ok'}
    except Exception as exp:
        logger.exception('Screen streaming')
        data = {'status': 'failed', 'message': str(exp)}
    return send_response(data)

# AJAX


@require_http_methods(['POST'])
def touch(request):
    """Sending Touch Events."""
    data = {}
    try:
        env = Environment()
        x_axis = request.POST['x']
        y_axis = request.POST['y']
        if not is_number(x_axis) and not is_number(y_axis):
            logger.error('Axis parameters must be numbers')
            return invalid_params()
        args = ['input',
                'tap',
                x_axis,
                y_axis]
        trd = threading.Thread(target=env.adb_command,
                               args=(args, True))
        trd.daemon = True
        trd.start()
        data = {'status': 'ok'}
    except Exception as exp:
        logger.exception('Sending Touch Events')
        data = {'status': 'failed', 'message': str(exp)}
    return send_response(data)


# AJAX


@require_http_methods(['POST'])
def mobsf_ca(request, api=False):
    """Install and Remove MobSF Proxy RootCA."""
    data = {}
    try:
        env = Environment()
        action = request.POST['action']
        if action == 'install':
            env.install_mobsf_ca(action)
            data = {'status': 'ok', 'message': 'installed'}
        elif action == 'remove':
            env.install_mobsf_ca(action)
            data = {'status': 'ok', 'message': 'removed'}
        else:
            data = {'status': 'failed',
                    'message': 'Action not supported'}
    except Exception as exp:
        logger.exception('MobSF RootCA Handler')
        data = {'status': 'failed', 'message': str(exp)}
    return send_response(data, api)
