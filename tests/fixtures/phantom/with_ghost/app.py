import os
import json

import helper
import ghostlib


def use():
    return helper.helped(os.sep, json.dumps([]), ghostlib.now())
