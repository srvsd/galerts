# TODO documentation
# Copyright (c) 2011 Josh Bronson
#               2015 Sarvesh Kumar <skmrx@opmbx.org>
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
import json
import urllib2
from datetime import datetime
from BeautifulSoup import BeautifulSoup
from getpass import getpass
from urllib import urlencode
from json.decoder import JSONDecoder

class AlertParameter:
    """
    A named parameter for an alert and its permissible values.
    """
    def __init__(self):
        self.values = {}

    def add(self, value, name):
        """
        Add a known permissible value of the parameter.
        
        This stores a map from the value to its name.
        Returns value itself.
        """
        self.values[value] = name
        return value

    def getName(self, value):
        """
        Get the name of a known value.
        """
        if value in self.values:
            return self.values[value]
        else:
            return None

    def getKnownPermissibleValues(self):
        """
        Get the possible values for this parameter
        """
        return self.values.keys()

###############################################################################
# Parameters for the alerts and their known permissible values. Note that since
# Google might add new parameter values in the future, there's no strict
# checking of whether values lie in the known range.
#
# But it is always better to use the named version of the parameter. For
# example, using Sources.Discussions instead of the value 7
#
###############################################################################
#
# Sources of data for alerts
Sources = AlertParameter()
Sources.Automatic   = Sources.add(0, "Automatic")
Sources.Blogs       = Sources.add(1, "Blogs")
Sources.News        = Sources.add(2, "News")
Sources.Web         = Sources.add(3, "Web")
Sources.Video       = Sources.add(5, "Video")
Sources.Books       = Sources.add(6, "Books")
Sources.Discussions = Sources.add(7, "Discussions")
    
# Volume of alerts
Volumes = AlertParameter()
Volumes.AllResults  = Volumes.add(2, "All results")
Volumes.BestResults = Volumes.add(3, "Only the best results")

# Delivery Types for alerts
DeliveryTypes = AlertParameter()
DeliveryTypes.Email = DeliveryTypes.add(1, "email")
DeliveryTypes.Feed  = DeliveryTypes.add(2, "RSS feed")

# Frequency of alerts
Frequencies = AlertParameter()
Frequencies.AsItHappens = Frequencies.add(1, "As-it-happens")
Frequencies.OnceADay    = Frequencies.add(2, "At most once a day")
Frequencies.OnceAWeek   = Frequencies.add(3, "At most once a week")
#########################################################

# For now, only the google.com endpoint is supported
_REGION = 'US'
_REGION_DOMAIN = 'com'
_GOOGLE_DOMAIN = 'google.' + _REGION_DOMAIN

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
        self.resp_status  = status
        self.resp_headers = headers
        self.resp_body    = body

class ParseFailureError(Exception):
    """
    Raised when a Google Alerts feature is used that is not supported in this code.
    """

class Account:
    """
    Account related information in window.STATE
    """
    def __init__(self, account_data):
        self.email         = account_data[2]
        self.delivery_data = account_data[3]
        self.language      = account_data[5]
        self.account_id    = account_data[14]

class Alert:
    """
    Represents the state of an alert in WindowState
    """

    def __init__(self, alert_state):
        self.alert_id   = alert_state[1]
        self.account_id = alert_state[3]
        
        alert_data      = alert_state[2]

        (query_info, source_info, volume_info, delivery_infos) = alert_data[3:7]

        self.query      = query_info[1]
        self.language   = query_info[3][1]
        self.region     = query_info[3][2]

        # sources is None for Automatic
        self.sources = source_info
        self.volume  = volume_info

        # support only one mode of delivery for now, but it looks like Google
        # Alerts can support mutliple of them in the future since there is an
        # array of delivery infos
        delivery_info   = delivery_infos[0]

        self.frequency  = delivery_info[4]
        self.delivery   = delivery_info[1]
        self.email      = delivery_info[2]
        self.feed_id    = None
        self.feed_url   = None

        if self.delivery == DeliveryTypes.Feed:
            self.feed_id = delivery_info[11]
            self.feed_url = 'https://www.' + _GOOGLE_DOMAIN + '/alerts/feeds/' + self.account_id + '/' + self.feed_id

    def __str__(self):
        return '<Alert id: {}, query: {}, volume: {}, frequency: {}, delivery: {}, email: {}, feed: {}>'.format(
            self.alert_id, self.query, Volumes.getName(self.volume), Frequencies.getName(self.frequency),
            DeliveryTypes.getName(self.delivery), self.email, self.feed_url)

class WindowState:
    """
    Represents the window.STATE variable in the Google Alerts page.
    
    This variable is a Javascript array containing all information regarding
    every alert, information about the logged in user account and some other 
    information as well.
    """
    def __init__(self, window_state):
        # 'x' is a parameter that needs to be sent with every request. Every time
        # the window state is refreshed, a new 'x' will be received.
        self.x = window_state[3]

        alerts_data = window_state[1]

        if alerts_data is not None:
            # There is atleast one alert
            alerts = alerts_data[1]
            self.alerts = [ Alert(alert_data) for alert_data in alerts ]
        else:
            self.alerts = []

        accounts_data = window_state[2]
        accounts_list = accounts_data[6]

        self.accounts = {}

        for account_data in accounts_list:
            account = Account(account_data)
            self.accounts[account.email] = account

class GoogleAlertsManager(object):
    """
    Manages creation, modification, and deletion of Google Alerts for the
    Google account associated with *email*.

    Resorts to html scraping because no public API has been released.

    Note: multiple email addresses can be associated with a single Google
    account, and if a user with multiple email addresses associated with her
    Google account signs into the web interface, it will allow her to set the
    delivery of email alerts to any of her associated email addresses. However,
    for now, :class:`GoogleAlertsManager` always uses the email address it's
    instantiated with when creating new email alerts or changing feed alerts
    to email alerts.
    """

    def __init__(self, email, password):
        """
        :param email: sign in using this email address. If there is no @
            symbol in the value, "@gmail.com" will be appended.
        :param password: plaintext password, used only to get a session
            cookie. Sent over a secure connection and then discarded.

        :raises SignInError: if Google responds with "403 Forbidden" to
            our request to sign in
        :raises UnexpectedResponseError: if the status code of Google's
              response is unrecognized (neither 403 nor 200)
        :raises socket.error: e.g. if there is no network connection
        """
        if '@' not in email:
            email += '@gmail.com'
        self.email = email
        self.opener = urllib2.build_opener(urllib2.HTTPCookieProcessor())

        urllib2.install_opener(self.opener)

        self._signin(password)
        self._refresh_window_state()

    def _signin(self, password):
        """
        Obtains a cookie from Google for an authenticated session.
        """
        login_page_url   = 'https://accounts.' + _GOOGLE_DOMAIN + '/ServiceLogin'
        authenticate_url = 'https://accounts.' + _GOOGLE_DOMAIN + '/ServiceLoginAuth'

        # Load login page
        login_page_contents = self.opener.open(login_page_url).read()

        # Find GALX value
        galx_match_obj = re.search(
            r'name="GALX" type="hidden"\n*\t*\s*value="(.*)"',
            login_page_contents,
            re.IGNORECASE,
            )
        galx_value = galx_match_obj.group(1) \
            if galx_match_obj.group(1) is not None else ''

        params = urlencode({
            'Email': self.email,
            'Passwd': password,
            'service': 'alerts',
            'continue': 'https://www.' + _GOOGLE_DOMAIN + '/alerts?hl=en&gl=us',
            'GALX': galx_value,
            })
        response = self.opener.open(authenticate_url, params)
        resp_code = response.getcode()
        final_url = response.geturl()
        body = response.read()

        if resp_code == 403 or final_url == authenticate_url:
            raise SignInError(
                'Got 403 Forbidden; bad email/password combination?'
                )

        if resp_code != 200:
            raise UnexpectedResponseError(
                resp_code,
                response.info().headers,
                body,
                )

    def _refresh_window_state(self):
        """
        The alerts and other required data for managing alerts are stored as a
        Javascript array in window.STATE.

        Returns: The parsed value of window.STATE
        """

        alerts_url = 'https://www.' + _GOOGLE_DOMAIN + '/alerts?hl=en&gl=us'
        response = self.opener.open(alerts_url)
        resp_code = response.getcode()
        body = response.read()
   
        if resp_code != 200:
            raise UnexpectedResponseError(resp_code, [], body)

        soup = BeautifulSoup(body, convertEntities=BeautifulSoup.HTML_ENTITIES)

        # the alerts data is stored in window.STATE defined in one of the
        # <script> tags 
        script = soup.find('script', text=re.compile(r'window\.STATE\s*='))
        state_value_match = re.search(r'window\.STATE\s*=\s*(.*)', script.string)

        if state_value_match is None:
            raise ParseFailureError("Couldn't find the definition of window.STATE in the Google Alerts page")

        state_value_string = state_value_match.group(1)

        state_value = JSONDecoder().raw_decode(state_value_string)[0]
        self.window_state = WindowState(state_value)
        self.account = self.window_state.accounts[self.email]

    @property
    def alerts(self):
        """
        Return a list of :class:`ArrayState` objects which contain information about all the alerts.
        """
        self._refresh_window_state()
        return self.window_state.alerts[:]

    def _create_alert_data(self, query, sources, delivery, freq, vol, lang='en', region=None):
        """
        Create data for a single alert which is used for API calls
        """
        if sources is not None:
            if Sources.Automatic in sources:
                raise ValueError('List of sources cannot contain Sources.Automatic')

        delivery_block = None
        if freq != Frequencies.AsItHappens:
            utcnow = datetime.utcnow()

            delivery_block = [ None, None, utcnow.hour ]

            if freq == Frequencies.OnceAWeek:
                delivery_block += [ (utcnow.weekday()+1)%7 ] # weekday() sets Monday as 0, but Google Alerts want Sunday as 0

        alert_data = [
                None, None, None,
                [
                    None,
                    query,
                    _REGION_DOMAIN,
                    [
                        None,
                        lang,
                        region if region is not None else _REGION
                    ],
                    None, None, None,
                    0 if region is None else 1, # Denotes whether the region is 'Any region'
                    1  #FIXME unknown
                ],
                sources,
                vol,
                [
                    [
                        None,
                        delivery,
                        self.account.email if delivery == DeliveryTypes.Email else '',
                        delivery_block,
                        freq,
                        self.account.language,
                        None, None, None, None, None,
                        '0',
                        None, None,
                        self.account.account_id
                    ]
                ]
            ]

        return alert_data

    def create(self, query, sources=None, delivery=DeliveryTypes.Feed, freq=None, vol=Volumes.BestResults, lang='en', region=None):
        #TODO fix doc
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

        url = 'https://www.' + _GOOGLE_DOMAIN + '/alerts/create?x=' + self.window_state.x

        if delivery == DeliveryTypes.Feed:
            if freq is None:
                freq = Frequencies.AsItHappens

            if freq != Frequencies.AsItHappens:
                raise ValueError('Frequency for a feed can can only be Frequencies.AsItHappens, but was set to ' + str(freq)) 
        else:
            if freq is None:
                freq = Frequencies.OnceADay

        params = [
            None,
            self._create_alert_data(
                query    = query,
                sources  = sources,
                delivery = delivery,
                freq     = freq,
                vol      = vol,
                lang     = lang,
                region   = region
            )
        ]

        post_params = urlencode({ 'params': json.dumps(params) })

        response = self.opener.open(url, post_params)
        resp_code = response.getcode()

        if resp_code != 200:
            raise UnexpectedResponseError(resp_code,
                response.info().headers,
                response.read(),
                )

    def update(self, alert):
        """
        Updates an existing alert which has been modified.
        """
        url = 'https://www.' + _GOOGLE_DOMAIN + '/alerts/modify?x=' + self.window_state.x

        params = [
            None,
            alert.alert_id,
            self._create_alert_data(
                query    = alert.query,
                sources  = alert.sources,
                delivery = alert.delivery,
                freq     = alert.frequency,
                vol      = alert.volume,
                lang     = alert.language,
                region   = alert.region
            )
        ]

        post_params = urlencode({ 'params': json.dumps(params) })

        response = self.opener.open(url, post_params)
        resp_code = response.getcode()
        if resp_code != 200:
            raise UnexpectedResponseError(
                resp_code,
                response.info().headers,
                response.read(),
                )

    def delete(self, alert):
        """
        Delete an existing alert.
        """
        url = 'https://www.' + _GOOGLE_DOMAIN + '/alerts/delete?x=' + self.window_state.x

        params = [
            None,
            alert.alert_id
        ]

        post_params = urlencode({ 'params': json.dumps(params) })

        response = self.opener.open(url, data=post_params)
        resp_code = response.getcode()
        if resp_code != 200:
            raise UnexpectedResponseError(
                resp_code,
                response.info().headers,
                response.read(),
                )

