import os
import os.path as osp
import requests
import shop.util.money as money
from . import core
from .util import fmt as fmt_money
from shop import Order, VERSION, make_order
from shop.util import money as money2
from shop.missing import nothing
from ..outside import gone


def via_name():
    make_order()


def via_module_attribute():
    core.make_order()


def via_alias():
    fmt_money(1)


def via_dotted_import():
    money.fmt(2)


def via_submodule_import():
    money2.fmt(3)


def constructor():
    Order()


def stdlib_alias():
    osp.join("a", "b")


def stdlib():
    os.getcwd()


def third_party():
    requests.get("http://x")


def builtin():
    len([])


def variable():
    print(VERSION)
