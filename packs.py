"""Themed word packs.

A pack swaps a room's categories for its own and plays only the letters it
has good answers for. An answer found in the pack's list for its category
is accepted straight away; anything else goes to the usual player vote, so
a real answer we forgot still has a chance.

Categories without a list here (e.g. "Name", "Animal") are checked the
classic way in utils.get_answer_validity.

Keep every list family-friendly: these are shown at public events.
"""

import re


def _words(text):
    return {_key(w) for w in text.split(",") if w.strip()}


def _key(word):
    """How answers are matched: case, spaces, dots, dashes and underscores
    don't matter, so "url_for", "url for" and "URL-For" are the same."""
    return re.sub(r"[\s._\-]+", "", word.lower())


PYTHON_AND_FLASK = _words("""
    abc, aiohttp, alembic, anaconda, api, app, append, args, argparse,
    assert, async, asyncio, attribute, await,
    babel, base64, bisect, black, blueprint, bool, boolean, bottle, break,
    bytes,
    celery, class, click, closure, collections, comprehension, conda,
    config, context, continue, cookie, coroutine, cors, cpython, csrf,
    cython,
    dataclass, datetime, debugger, decorator, def, del, deque, dict,
    dictionary, django, docker, docstring, dunder,
    elif, else, endpoint, enum, enumerate, environ, escape, except,
    exception, extension,
    fastapi, finally, fixture, flake8, flask, float, for, format, frozenset,
    fstring, function, functools,
    garbage collector, generator, get, getattr, gevent, gil, git, global,
    gunicorn,
    hash, hashlib, header, heapq, hook, html, http,
    if, import, in, init, input, int, integer, interpreter, is, isinstance,
    iterable, iterator, itertools, itsdangerous,
    jinja, jinja2, jit, join, json, jsonify, jupyter,
    key, keyerror, keyword, kwargs,
    lambda, len, linter, list, local, localhost, logging, loop,
    main, map, markupsafe, marshmallow, matplotlib, metaclass, method,
    middleware, migrate, module, mypy,
    namedtuple, namespace, none, nonlocal, not, numpy,
    object, open, or, orm, os, override,
    package, pallets, pandas, pass, pathlib, pep, pep8, pickle, pip, poetry,
    print, property, pydantic, pyenv, pypi, pyproject, pytest, python,
    quart, query, queue, quickstart,
    raise, range, redirect, redis, regex, render, render_template, repl,
    request, requests, response, return, route,
    self, session, set, signal, slice, socketio, sorted, sqlalchemy, sqlite,
    static, staticmethod, str, string, super, sys,
    template, test, threading, toml, tornado, tox, traceback, try, tuple,
    type, typing,
    unicode, unittest, url_for, urllib, utf8, uv, uvicorn, uwsgi,
    variable, vars, venv, version, view, virtualenv,
    waitress, websocket, werkzeug, wheel, while, with, wsgi, wtforms,
    xml,
    yaml, yield,
    zen, zip, zipfile
""")

LAGOS_AND_AFRICA = _words("""
    abeokuta, abuja, accra, addis ababa, adire, afrobeats, agbada, agege,
    ajah, akara, alaba, amala, ankara, apapa, asaba,
    badagry, bamako, banga, beans, benin, bitterleaf, bole, botswana, buka,
    bukka,
    cairo, calabar, cameroon, cassava, chin chin, cocoa,
    dakar, danfo, dashiki, djembe, dodo, durban,
    eba, ebute metta, efo, egusi, egypt, eko, enugu, epe, ethiopia, ewedu,
    falomo, festac, freetown, fufu, fura,
    gambia, gari, garri, gbegiri, gele, ghana, gidi,
    harare, highlife,
    ibadan, ijebu, ikeja, ikorodu, ikoyi, ilorin, iru, isale eko,
    iyana ipaja,
    johannesburg, jollof, juju,
    kampala, kano, keke, kente, kenya, kigali, kilimanjaro, kilishi,
    kuli kuli, kunu,
    lafun, lagoon, lagos, lekki, lome, luanda, lusaka,
    makoko, mali, mandazi, maputo, marina, maryland, moi moi, mombasa,
    mushin,
    naija, nairobi, namibia, niger, nigeria, nkwobi, nollywood,
    oba, obalende, ofada, ogbono, ojota, ojuelegba, okada, onitsha, oshodi,
    owambe,
    palm wine, pepper soup, plantain, port harcourt, pounded yam, puff puff,
    rabat, rwanda,
    sahara, senegal, serengeti, shoki, surulere, suya,
    tanzania, third mainland bridge, timbuktu, tunis, tuwo,
    ubuntu, uganda, ugu, ukodo, uyo,
    victoria falls, victoria island,
    waakye, warri, wuse,
    yaba, yam, yaounde, yoruba,
    zambia, zanzibar, zaria, zimbabwe, zobo
""")


PACKS = {
    "flaskcon": {
        "name": "FlaskCon",
        "categories": ["Name", "Animal", "Python & Flask", "Lagos & Africa"],
        # Letters with plenty of answers in every category above.
        "letters": "ABCDEFGIJKLMNOPRSTWY",
        "default_rounds": 6,
        "words": {
            "Python & Flask": PYTHON_AND_FLASK,
            "Lagos & Africa": LAGOS_AND_AFRICA,
        },
    },
}


def get_pack(pack_id):
    return PACKS.get(pack_id) if isinstance(pack_id, str) else None


def pack_word_status(pack_id, category, word):
    """"valid" or "needs_vote" for a category this pack has a list for,
    or None if the pack doesn't cover the category."""
    pack = get_pack(pack_id)
    if not pack or category not in pack["words"]:
        return None
    return "valid" if _key(word) in pack["words"][category] else "needs_vote"
