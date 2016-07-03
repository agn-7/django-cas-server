# -*- coding: utf-8 -*-
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU General Public License version 3 for
# more details.
#
# You should have received a copy of the GNU General Public License version 3
# along with this program; if not, write to the Free Software Foundation, Inc., 51
# Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#
# (c) 2016 Valentin Samir
"""federated mode helper classes"""
from .default_settings import settings

from .cas import CASClient
from .models import FederatedUser, FederateSLO, User

from importlib import import_module
from six.moves import urllib

SessionStore = import_module(settings.SESSION_ENGINE).SessionStore


class CASFederateValidateUser(object):
    """Class CAS client used to authenticate the user again a CAS provider"""
    username = None
    attributs = {}
    client = None

    def __init__(self, provider, service_url):
        self.provider = provider

        if provider in settings.CAS_FEDERATE_PROVIDERS:  # pragma: no branch (should always be True)
            (server_url, version) = settings.CAS_FEDERATE_PROVIDERS[provider][:2]
            self.client = CASClient(
                service_url=service_url,
                version=version,
                server_url=server_url,
                renew=False,
            )

    def get_login_url(self):
        """return the CAS provider login url"""
        return self.client.get_login_url() if self.client is not None else False

    def get_logout_url(self, redirect_url=None):
        """return the CAS provider logout url"""
        return self.client.get_logout_url(redirect_url) if self.client is not None else False

    def verify_ticket(self, ticket):
        """test `ticket` agains the CAS provider, if valid, create the local federated user"""
        if self.client is None:  # pragma: no cover (should not happen)
            return False
        try:
            username, attributs = self.client.verify_ticket(ticket)[:2]
        except urllib.error.URLError:
            return False
        if username is not None:
            if attributs is None:
                attributs = {}
            attributs["provider"] = self.provider
            self.username = username
            self.attributs = attributs
            try:
                user = FederatedUser.objects.get(
                    username=username,
                    provider=self.provider
                )
                user.attributs = attributs
                user.ticket = ticket
                user.save()
            except FederatedUser.DoesNotExist:
                user = FederatedUser.objects.create(
                    username=username,
                    provider=self.provider,
                    attributs=attributs,
                    ticket=ticket
                )
                user.save()
            return True
        else:
            return False

    @staticmethod
    def register_slo(username, session_key, ticket):
        """association a ticket with a (username, session) for processing later SLO request"""
        FederateSLO.objects.create(
            username=username,
            session_key=session_key,
            ticket=ticket
        )

    def clean_sessions(self, logout_request):
        """process a SLO request"""
        try:
            slos = self.client.get_saml_slos(logout_request) or []
        except NameError:  # pragma: no cover (should not happen)
            slos = []
        for slo in slos:
            for federate_slo in FederateSLO.objects.filter(ticket=slo.text):
                session = SessionStore(session_key=federate_slo.session_key)
                session.flush()
                try:
                    user = User.objects.get(
                        username=federate_slo.username,
                        session_key=federate_slo.session_key
                    )
                    user.logout()
                    user.delete()
                except User.DoesNotExist:  # pragma: no cover (should not happen)
                    pass
                federate_slo.delete()
