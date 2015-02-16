# Copyright (c) 2011 Josh Bronson
#
# Permission is hereby granted, free of charge, to any person
# obtaining a copy of this software and associated documentation
# files (the "Software"), to deal in the Software without
# restriction, including without limitation the rights to use,
# copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the
# Software is furnished to do so, subject to the following
# conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES
# OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
# HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
# WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
# FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
# OTHER DEALINGS IN THE SOFTWARE.

import re
import urllib2
import galerts2
from galerts2 import Sources, Volumes, DeliveryTypes, Frequencies
from BeautifulSoup import BeautifulSoup
from getpass import getpass
from urllib import urlencode

# {{{ these values must match those used in the Google Alerts web interface:

#: The maximum length of an alert query
QUERY_MAXLEN = 2048

#: Use this value to indicate delivery via email
DELIVER_EMAIL = 'Email'
#: Use this value to indicate delivery via feed
DELIVER_FEED = 'feed'
DELIVER_DEFAULT_VAL = DeliveryTypes.Feed
#: maps available delivery types to the values Google uses for them
DELIVER_TYPES = {
    DELIVER_EMAIL: DeliveryTypes.Email,
    DELIVER_FEED: DELIVER_DEFAULT_VAL,
    }
DELIVER_TYPES_REV = { v: k for (k, v) in DELIVER_TYPES.items() }

#: Use this value for :attr:`Alert.freq` to indicate delivery in real time
FREQ_AS_IT_HAPPENS = 'As-it-happens'
#: Use this value for :attr:`Alert.freq` to indicate delivery once a day
FREQ_ONCE_A_DAY = 'Once a day'
#: Use this value for :attr:`Alert.freq` to indicate delivery once a week
FREQ_ONCE_A_WEEK = 'Once a week'
#: maps available alert frequencies to the values Google uses for them
ALERT_FREQS = {
    FREQ_AS_IT_HAPPENS: Frequencies.AsItHappens,
    FREQ_ONCE_A_DAY: Frequencies.OnceADay,
    FREQ_ONCE_A_WEEK: Frequencies.OnceAWeek,
    }
ALERT_FREQS_REV = { v: k for (k, v) in ALERT_FREQS.items() }

#: Use this value for an alert volume of only the best results
VOL_ONLY_BEST = 'Only the best results'
#: Use this value for an alert volume of all results
VOL_ALL = 'All results'
#: maps available alert volumes to the values Google uses for them
ALERT_VOLS = {
    VOL_ONLY_BEST: Volumes.BestResults,
    VOL_ALL: Volumes.AllResults,
    }
ALERT_VOLS_REV = { v: k for (k, v) in ALERT_VOLS.items() }

#: Use this value for :attr:`Alert.type` to indicate all results
TYPE_EVERYTHING = 'Everything'
#: Use this value for :attr:`Alert.type` to indicate news results
TYPE_NEWS = 'News'
#: Use this value for :attr:`Alert.type` to indicate blog results
TYPE_BLOGS = 'Blogs'
#: Use this value for :attr:`Alert.type` to indicate realtime results
TYPE_REALTIME = 'Realtime'
#: Use this value for :attr:`Alert.type` to indicate video results
TYPE_VIDEO = 'Video'
#: Use this value for :attr:`Alert.type` to indicate discussion results
TYPE_DISCUSSIONS = 'Discussions'
#: Use this value for :attr:`Alert.type` to indicate book results
TYPE_BOOKS = 'Books'
#: maps available alert types to the values Google uses for them
ALERT_TYPES = {
    TYPE_EVERYTHING: Sources.Automatic,
    TYPE_NEWS: Sources.News,
    TYPE_BLOGS: Sources.Blogs,
    TYPE_REALTIME: Sources.Web,  # FIXME Not really sure if REALTIME corresponds to Web
    TYPE_VIDEO: Sources.Video,
    TYPE_DISCUSSIONS: Sources.Discussions,
    TYPE_BOOKS: Sources.Books
    }
ALERT_TYPES_REV = { v: k for (k, v) in ALERT_TYPES.items() }
# }}}

class SignInError(Exception):
    """
    Raised when Google sign in fails.
    """

class UnexpectedResponseError(Exception):
    """
    Raised when Google's response to a request is unrecognized.
    """
    def __init__(self, status, headers, body):
        Exception.__init__(self)
        self.resp_status = status
        self.resp_headers = headers
        self.resp_body = body

class Alert(object):
    """
    Models a Google Alert.

    You should not create :class:`Alert` objects explicitly; the
    :class:`GAlertsManager` will create them for you. You can then access
    alert objects via :attr:`GAlertsManager.alerts` to e.g. update their
    attributes and pass them back to the manager for saving. To create a new
    alert, use :attr:`GAlertsManager.create`, and when you next access
    :attr:`GAlertsManager.alerts` you'll find an :class:`Alert` object there
    for the alert you just created.
    """
    def __init__(self, email, s, query, type, freq, vol, deliver, feedurl=None):
        assert type in ALERT_TYPES
        assert freq in ALERT_FREQS
        assert vol in ALERT_VOLS
        assert deliver in DELIVER_TYPES
        self._email = email
        self._s = s
        self._query = query
        self._type = type
        self._freq = freq
        self._vol = vol
        self._deliver = deliver
        self._feedurl = feedurl

    def _query_get(self):
        return self._query

    def _query_set(self, value):
        if len(value) > QUERY_MAXLEN:
            raise ValueError('Illegal value for Alert.query (must be at most '
                '%d characters): %r' % (QUERY_MAXLEN, value))
        if not isinstance(value, unicode):
            try:
                value = unicode(value)
            except UnicodeDecodeError:
                raise ValueError('Illegal value for Alert.query ' \
                    '(unicode(value) failed): %r' % value)
        self._query = value

    query = property(_query_get, _query_set, doc="""\
        The search terms this alert will match.

        :raises ValueError: if value is not ``unicode`` or ``unicode(value)``
            fails, or if its length exceeds :attr:`QUERY_MAXLEN`
        """)

    def _deliver_get(self):
        return self._deliver

    def _deliver_set(self, value):
        if value not in DELIVER_TYPES:
            raise ValueError('Illegal value for Alert.deliver: %r' % value)
        self._deliver = value

    deliver = property(_deliver_get, _deliver_set, doc="""\
        The delivery method for this alert.

        :raises ValueError: if value is not in :attr:`DELIVER_TYPES`
        """)

    def _freq_get(self):
        return self._freq

    def _freq_set(self, value):
        if value not in ALERT_FREQS:
            raise ValueError('Illegal value for Alert.freq: %r' % value)
        self._freq = value

    freq = property(_freq_get, _freq_set, doc="""\
        The frequency with which results are delivered for this alert.

        :raises ValueError: if value is not in :attr:`ALERT_FREQS`
        """)

    def _vol_get(self):
        return self._vol

    def _vol_set(self, value):
        if value not in ALERT_VOLS:
            raise ValueError('Illegal value for Alert.vol: %r' % value)
        self._vol = value

    vol = property(_vol_get, _vol_set, doc="""\
        The volume of results delivered for this alert.

        :raises ValueError: if value is not in :attr:`ALERT_VOLS`
        """)

    def _type_get(self):
        return self._type

    def _type_set(self, value):
        if value not in ALERT_TYPES:
            raise ValueError('Illegal value for Alert.type: %r' % value)
        self._type = value

    type = property(_type_get, _type_set, doc="""\
        The type of the results this alert delivers.

        :raises ValueError: if value is not in :attr:`ALERT_TYPES`
        """)

    @property
    def email(self):
        """
        Returns the email address of the manager that created this alert.
        """
        # XXX support Google accounts with multiple email addresses?
        return self._email

    @property
    def feedurl(self):
        """
        For feed alerts, returns the url of the feed results are delivered to.
        For email alerts, returns ``None``.

        **Note:** If you change an :class:`Alert` object from a feed alert to
        an email alert (or vice versa) via :attr:`Alert.deliver`, the value of
        :attr:`Alert.feedurl` is not updated. You must pass the alert to
        :attr:`GAlertsManager.update` to save the changes and then get a
        fresh :class:`Alert` object from :attr:`GAlertsManager.alerts` to get
        the up-to-date feed url.
        """
        return self._feedurl

    def __hash__(self):
        return hash((self._s, self.query, self.type, self.freq, self.deliver,
            self._feedurl))

    def __eq__(self, other):
        return all(getattr(self, attr) == getattr(other, attr) for attr in
            ('_s', 'query', 'type', 'freq', 'deliver', '_feedurl'))

    def __repr__(self):
        return '<%s for "%s" at %s>' % (self.__class__.__name__,
            self.query.encode('utf-8'), hex(id(self)))

    def __str__(self):
        return '<%s query="%s" type="%s" freq="%s" deliver="%s">' % (
            self.__class__.__name__,
            self.query.encode('utf-8'), self.type, self.freq, self.deliver)


class GAlertsManager(galerts2.GoogleAlertsManager):
    """
    Manages creation, modification, and deletion of Google Alerts for the
    Google account associated with *email*.

    Resorts to html scraping because no public API has been released.

    Note: multiple email addresses can be associated with a single Google
    account, and if a user with multiple email addresses associated with her
    Google account signs into the web interface, it will allow her to set the
    delivery of email alerts to any of her associated email addresses. However,
    for now, :class:`GAlertsManager` always uses the email address it's
    instantiated with when creating new email alerts or changing feed alerts
    to email alerts.
    """

    @property
    def alerts(self):
        """
        Queries Google on every access for the alerts associated with this
        account, wraps them in :class:`Alert` objects, and returns a generator
        you can use to iterate over them.
        """
        
        # new style alerts. these will be converted to objects of the
        # galerts.Alert class
        new_alerts = super(GAlertsManager, self).alerts

        for new_alert in new_alerts:
            alert = Alert(
                email   = self.email,
                s       = new_alert.alert_id,
                query   = new_alert.query,
                type    = ALERT_TYPES_REV[new_alert.sources[0]] if new_alert.sources is not None else ALERT_TYPES_REV[Sources.Automatic],
                freq    = ALERT_FREQS_REV[new_alert.frequency],
                vol     = ALERT_VOLS_REV[new_alert.volume],
                deliver = DELIVER_TYPES_REV[new_alert.delivery],
                feedurl = new_alert.feed_url
            )

            alert.new_alert = new_alert

            yield alert

    def create(self, query, type, feed=True, freq=FREQ_ONCE_A_DAY,
            vol=VOL_ONLY_BEST):
        """
        Creates a new alert.

        :param query: the search terms the alert will match
        :param type: a value in :attr:`ALERT_TYPES`
        :param feed: whether to deliver results via feed or email
        :param freq: a value in :attr:`ALERT_FREQS` indicating how often results
            should be delivered; used only for email alerts (feed alerts are
            updated in real time). Defaults to :attr:`FREQ_ONCE_A_DAY`.
        :param vol: a value in :attr:`ALERT_VOLS` indicating volume of results
            to be delivered. Defaults to :attr:`VOL_ONLY_BEST`.
        """

        super(GAlertsManager, self).create(
            query    = query,
            sources  = [ ALERT_TYPES[type] ] if ALERT_TYPES[type] != Sources.Automatic else None,
            delivery = DeliveryTypes.Feed if feed else DeliveryTypes.Email,
            freq     = ALERT_FREQS[FREQ_AS_IT_HAPPENS if feed else freq],
            vol      = ALERT_VOLS[vol]
        )

    def update(self, alert):
        """
        Updates an existing alert which has been modified.
        """
        alert.new_alert.delivery  = DELIVER_TYPES[alert.deliver]
        alert.new_alert.query     = alert.query
        alert.new_alert.sources   = [ ALERT_TYPES[alert.type] ] if ALERT_TYPES[alert.type] != Sources.Automatic else None
        alert.new_alert.volume    = ALERT_VOLS[alert.vol]
        alert.new_alert.frequency = ALERT_FREQS[alert.freq]

        super(GAlertsManager, self).update(alert.new_alert)

    def delete(self, alert):
        """
        Deletes an existing alert.
        """
        super(GAlertsManager, self).delete(alert.new_alert)

def main():
    import socket
    import sys
    TERMINAL_ENCODING = sys.stdin.encoding

    print 'Google Alerts Manager\n'
    try:
        while True:
            email = raw_input('email: ')
            password = getpass('password: ')
            try:
                gam = GAlertsManager(email, password)
                break
            except SignInError:
                print '\nSign in failed, try again or hit Ctrl-C to quit\n'
            except socket.error:
                print '\nCould not connect to Google. Check your network ' \
                    'connection and try again, or hit Ctrl-C to quit\n'

        def print_alerts(alerts):
            print
            print ' #   Query                Type           How often       Volume                    Deliver to'
            print ' =   =====                ====           =========       ======                    =========='
            for i, alert in enumerate(alerts):
                query = alert.query
                if len(query) > 20:
                    query = query[:17] + '...'
                type = alert.type
                freq = alert.freq
                vol = alert.vol
                deliver = alert.deliver
                if deliver == DELIVER_FEED:
                    deliver = alert.feedurl
                num = '%d' % i
                print num.rjust(2), ' ', query.ljust(20), type.ljust(14), freq.ljust(15), vol.ljust(25), deliver

        def prompt_type(default=None):
            while True:
                print '  Alert type:'
                print '\n'.join('    %s. %s' % (v, k) for (k, v) in sorted(
                    ALERT_TYPES.iteritems(), key=lambda i: int(i[1])))
                if default is not None:
                    prompt = '    Choice (<Enter> for "%s"): ' % default
                else:
                    prompt = '    Choice: '
                type = int(raw_input(prompt))
                for k, v in ALERT_TYPES.iteritems():
                    if v == type:
                        return k
                if default is not None:
                    return default
                print '  Invalid type, try again\n'

        def prompt_vol(default=None):
            while True:
                print '  Alert volume:'
                print '\n'.join('    %s. %s' % (v, k) for (k, v) in sorted(
                    ALERT_VOLS.iteritems(), key=lambda i: int(i[1])))
                if default is not None:
                    prompt = '    Choice (<Enter> for "%s"): ' % default
                else:
                    prompt = '    Choice: '
                vol = int(raw_input(prompt))
                for k, v in ALERT_VOLS.iteritems():
                    if v == vol:
                        return k
                if default is not None:
                    return default
                print '  Invalid volume, try again\n'

        def prompt_alert(alerts):
            while True:
                try:
                    choice = int(raw_input('\n  Choice: '))
                    return alerts[choice]
                except (ValueError, IndexError):
                    print '  Bad input: enter a number from 0 to %d' % (len(alerts) - 1)

        def prompt_query(default=None):
            if isinstance(default, unicode):
                default = default.encode('utf-8')
            while True:
                if default is not None:
                    prompt = '  Query (<Enter> for "%s"): ' % default
                else:
                    prompt = '  Query: '
                query = raw_input(prompt)
                query = query.decode(TERMINAL_ENCODING)
                if len(query) > QUERY_MAXLEN:
                    print '  Query must be at most %d characters, try again\n' \
                        % QUERY_MAXLEN
                    continue
                if query:
                    return query
                if default is not None:
                    return default
                print '  Query must be at least 1 character, try again\n'

        def prompt_deliver(current=None):
            if current is None:
                if raw_input('  Deliver to [F]eed or [e]mail? (F/e): ') != 'e':
                    return DELIVER_FEED
                return DELIVER_EMAIL
            if current == DELIVER_EMAIL:
                if raw_input('  Switch to feed delivery (y/N)? ') == 'y':
                    return DELIVER_FEED
                return DELIVER_EMAIL
            if raw_input('  Switch to email delivery (y/N)? ') == 'y':
                return DELIVER_EMAIL
            return DELIVER_FEED

        def prompt_freq(default=None):
            while True:
                print '  Alert frequency:'
                print '\n'.join('    %s. %s' % (v, k) for (k, v) in sorted(
                    ALERT_FREQS.iteritems(), key=lambda i: int(i[1])))
                if default is not None:
                    prompt = '    Choice (<Enter> for "%s"): ' % default
                else:
                    prompt = '    Choice: '
                freq = int(raw_input(prompt))
                for k, v in ALERT_FREQS.iteritems():
                    if v == freq:
                        return k
                if default is not None:
                    return default
                print '  Invalid frequency, try again\n'


        ACTIONS = ('List Alerts', 'Create Alert', 'Edit Alert', 'Delete Alert', 'Quit')
        while True:
            print '\nActions:'
            print '\n'.join('  %d. %s' % (i, v) for (i, v) in enumerate(ACTIONS))
            action = raw_input('  Choice: ')
            try:
                action = int(action)
                action = ACTIONS[action]
            except (ValueError, IndexError):
                print 'Bad input: enter a number from 0 to %d\n' % (len(ACTIONS) - 1)
                continue

            print '\n%s' % action

            if action == 'Quit':
                break

            if action == 'List Alerts':
                alerts = list(gam.alerts)
                print_alerts(alerts)

            elif action == 'Create Alert':
                query = prompt_query()
                type = prompt_type()
                feed = prompt_deliver() == DELIVER_FEED
                freq = FREQ_AS_IT_HAPPENS if feed else prompt_freq()
                vol = prompt_vol()
                try:
                    gam.create(query, type, feed=feed, freq=freq, vol=vol)
                    print '\nAlert created.'
                except UnexpectedResponseError, e:
                    print '\nCould not create alert.'
                    import pdb; pdb.set_trace()

            elif action == 'Edit Alert':
                alerts = list(gam.alerts)
                print_alerts(alerts)
                alert = prompt_alert(alerts)
                alert.query = prompt_query(default=alert.query)
                alert.type = prompt_type(default=alert.type)
                alert.deliver = prompt_deliver(current=alert.deliver)
                alert.freq = FREQ_AS_IT_HAPPENS if alert.deliver != DELIVER_EMAIL \
                    else prompt_freq(default=alert.freq)
                alert.vol = prompt_vol(default=alert.vol)
                try:
                    gam.update(alert)
                    print '\nAlert modified.'
                except UnexpectedResponseError, e:
                    print '\nCould not modify alert.'
                    import pdb; pdb.set_trace()

            elif action == 'Delete Alert':
                alerts = list(gam.alerts)
                print_alerts(alerts)
                alert = prompt_alert(alerts)
                try:
                    gam.delete(alert)
                    print '\nAlert deleted.'
                except UnexpectedResponseError, e:
                    print '\nCould not delete alert.'
                    import pdb; pdb.set_trace()

            else:
                print 'code took unexpected branch... typo?'
    except (EOFError, KeyboardInterrupt):
        print
        return

if __name__ == '__main__':
    main()
