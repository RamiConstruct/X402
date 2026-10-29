"""Garde-fou : toute tentative réseau pendant les tests lève une erreur."""

import socket


class NetworkBlocked(AssertionError):
    pass


def _blocked(*_args, **_kwargs):
    raise NetworkBlocked("accès réseau interdit pendant les tests")


socket.create_connection = _blocked
socket.getaddrinfo = _blocked
socket.socket.connect = _blocked
socket.socket.connect_ex = _blocked
