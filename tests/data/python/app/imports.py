from __future__ import annotations

import os
import os.path as osp, json
from . import models
from ..core.settings import load as load_settings, DEBUG
from .models import (
    UserService,
    Repository as Repo,
)
from typing import *

try:
    import ujson
except ImportError:
    ujson = None


def lazy():
    from .. import utils
    return utils
