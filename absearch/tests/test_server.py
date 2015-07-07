import os
from collections import defaultdict

import gevent

from absearch import __version__
from absearch.tests.support import (runServers, stopServers, get_app, capture,
                                    test_config)
from absearch.server import reload, main


def setUp():
    runServers()


def tearDown():
    stopServers()


def test_info():
    app = get_app()

    # test the APIs
    info = app.get('/__info__').json
    assert info['version'] == __version__


def test_set_cohort():
    app = get_app()

    # get a cohort
    path = '/1/firefox/39/beta/en-US/US/default/default'
    res = app.get(path)

    assert 'cohort' not in res.json
    assert res.json['settings'] == {'searchDefault': 'Yahoo'}
    assert res.json['interval'] == 31536000


def test_default_interval():
    # en-US/FR does not exists. we fallback to the default in en-US
    # and if it does not contain an interval we want to add the default
    # interval
    app = get_app()
    path = '/1/Firefox/39/release/en-US/FR/default/default'
    res = app.get(path)
    assert 'cohort' not in res.json
    assert res.json['interval'] == 31536000


def test_set_cohort2():
    app = get_app()

    # get a cohort
    path = '/1/firefox/39/beta/cs-CZ/cz/default/default'
    res = app.get(path)

    cohort = res.json.get('cohort', 'default')
    assert cohort in ('default', 'foo23542', 'bar34234')
    settings = res.json['settings']

    # now that we have a cohort let's check back the settings
    path = '/1/firefox/39/beta/cs-CZ/cz/default/default/' + cohort
    res = app.get(path)
    assert res.json['settings'] == settings
    if 'cohort' not in res.json:
        wanted = ('Google1',)
    else:
        wanted = ('Google2', 'Google3')

    assert res.json['settings']['searchDefault'] in wanted
    # also, an unexistant cohort should fall back to the default
    # settings for the territory
    path = '/1/firefox/39/beta/cs-CZ/cz/default/default/meh'
    res = app.get(path)
    assert res.json['settings']['searchDefault'] == 'Google1'


def test_unexistant_territory():
    app = get_app()
    # check that an unexistant territory sends back the default
    # from the locale
    path = '/1/firefox/39/beta/fr-FR/uz/default/default'
    res = app.get(path).json
    assert res['settings']['searchDefault'] == 'GoogleD'


def test_unexistant_locale():
    app = get_app()
    # check that an unexistant locale sends back and interval
    path = '/1/firefox/39/beta/hh-FR/uz/default/default'

    res = app.get(path).json
    assert res.keys() == ['interval']


def test_max_cohort():
    # check that we can have at the most 3 users in the 'foo' cohort
    # that cohort is at 100% sampleRate for the fr territory under fr-FR
    app = get_app()

    # get the cohort 3 times
    path = '/1/firefox/39/beta/fr-FR/fr/default/default'
    for i in range(3):
        res = app.get(path)
        assert res.json['cohort'] == 'foo'

    # should be exausthed now, let's check we get a default now
    res = app.get(path)

    # when default we don't have the cohort key in the response
    assert 'cohort' not in res.json


def test_sample_rate():
    # de-DE has 4 cohorts. each one should represent 1% of the users
    # we're going to make 100 calls and see if we're around those percentages
    app = get_app()

    counts = defaultdict(int)

    # get the cohort 1000 times
    path = '/1/firefox/39/beta/de-DE/de/default/default'
    for i in range(1000):
        res = app.get(path)
        if 'cohort' not in res.json:
            counts['default'] += 1
        else:
            counts[res.json['cohort']] += 1

    # we should have around 10 users per cohort
    # and around 970 for the default
    assert 0 < counts['one'] <= 20, counts
    assert 0 < counts['two'] <= 20, counts
    assert 0 < counts['three'] <= 20, counts
    assert 955 <= counts['default'] <= 985, counts


def test_hb():
    app = get_app()
    res = app.get('/__heartbeat__')
    assert res.json == {}


def test_excluded():
    app = get_app()

    # make sure an excluded distribution falls back to
    # sending back just a 200 + interval
    path = '/1/firefox/39/beta/de-DE/de/ayeah/default'
    res = app.get(path).json
    assert res.keys() == ['interval']


def test_reload():
    # change some things in the config
    app = get_app()
    config_file = app.app._config_file
    config = app.app._config

    # save current config
    with open(config_file + '.saved', 'w') as f:
        config.write(f)

    # change the configuration to alternatives
    # so we actually test them
    config['statsd']['prefix'] = 'meh'
    config['sentry']['enabled'] = '1'
    config['absearch']['backend'] = 'directory'
    config['absearch']['counter'] = 'memory'
    datadir = os.path.join(os.path.dirname(__file__), '..', '..', 'data')
    config.add_section('directory')
    config['directory']['path'] = datadir

    # save new config
    with open(config_file, 'w') as f:
        config.write(f)

    try:
        # make sure that reload grabs the config
        with capture():
            reload()

        assert app.app._config['statsd']['prefix'] == 'meh'

        # doing a call with sentry disabled
        path = '/1/firefox/39/beta/hh-FR/uz/default/default'
        res = app.get(path).json
        assert res.keys() == ['interval']
    finally:
        # restore old config
        os.rename(config_file + '.saved', config_file)


def test_main():
    with capture():
        greenlet = gevent.spawn(main, [test_config])
        gevent.sleep(0.1)

    assert greenlet.started
    greenlet.kill()
    gevent.wait([greenlet])
    assert not greenlet.started
