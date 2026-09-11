"""Validate the existing Robot CI cookie; never trust client identity headers."""
import json
import os
import urllib.request
import urllib.error
from urllib.parse import urlsplit


class Unavailable(RuntimeError):
    pass


def check(cookie):
    # Use Robot CI's public session contract, not an optional integration patch.
    url = os.environ.get('PIPELINE_ROBOT_AUTH_URL', 'http://127.0.0.1:18082/api/auth/me')
    if url.endswith('/api/auth/pipeline'):
        url = url[:-len('/api/auth/pipeline')] + '/api/auth/me'
    parsed = urlsplit(url)
    if parsed.scheme != 'http' or parsed.hostname not in {'127.0.0.1', 'localhost', '::1'}:
        raise Unavailable('Robot CI authentication must use loopback')
    request = urllib.request.Request(url, headers={'Cookie': cookie or ''})
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        with opener.open(request, timeout=5) as response:
            data = json.loads(response.read(65537))
        user = data.get('user')
        return user if isinstance(user, str) and user.strip() else ''
    except urllib.error.HTTPError as error:
        if error.code in (401, 403):
            return ''
        raise Unavailable('Robot CI authentication unavailable') from error
    except (OSError, ValueError, AttributeError) as error:
        raise Unavailable('Robot CI authentication unavailable') from error


def username(cookie):
    try:
        return check(cookie)
    except Unavailable:
        return ''
