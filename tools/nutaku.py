"""Nutaku APK acquisition helper for resdown.

Flow (all public, no login):
    https://gi.nutaku.com/apk-info/<slug>            -> {"version":N,"url":...}
    <url>/../app-update/?type=apk                    -> 302 cdn1-dl.nutaku.net/.../<slug>_N.apk
    -> download, unzip, and let `resdown extract` pull Spine out.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request

from resdown import UA_DEFAULT, http_get


def apk_info(slug, ua=UA_DEFAULT, timeout=30, retries=3, opener=None):
    data, _ = http_get(f"https://gi.nutaku.com/apk-info/{slug}", ua=ua,
                       timeout=timeout, retries=retries, opener=opener)
    return json.loads(data.decode("utf-8", "replace"))


def apk_url(slug, ua=UA_DEFAULT, timeout=30, opener=None):
    """Resolve the direct .apk URL by following the app-update redirect."""
    info = apk_info(slug, ua=ua, timeout=timeout, opener=opener)
    page = info.get("url") or f"https://www.nutaku.net/games/{slug}/apk-update/"
    cand = urllib.parse.urljoin(page, "../app-update/?type=apk")
    req = urllib.request.Request(cand, headers={"User-Agent": ua})
    with (opener or urllib.request.build_opener()).open(req, timeout=timeout) as r:
        return r.geturl(), info.get("version")
