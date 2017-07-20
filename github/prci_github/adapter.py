import datetime
import logging
import time

from cachecontrol.adapter import CacheControlAdapter


logger = logging.getLogger(__name__)


class GitHubAdapter(CacheControlAdapter):
    """Handles GitHub request rate limit exhaustion and uses cachecontrol
    """
    def __init__(self, tries=3, *args, **kwargs):
        if not isinstance(tries, int) or tries <= 0:
            raise ValueError('tries must be positive integer')
        self.tries = tries

        super(GitHubAdapter, self).__init__(*args, **kwargs)

    def send(self, request, *args, **kwargs):
        # Force the caching mechanism to ignore max-age and send the request
        # with ETag. This way we get the freshest data without consuming
        # rate-limited requests
        # TODO: once cachecontrol containing fix from
        # https://github.com/ionrock/cachecontrol/pull/163
        # is available everywhere we care replace with following
        # it has the same effect but more suits better semantically
        # request.headers['cache-control'] = 'max-age=0'
        request.headers['cache-control'] = 'no-cache'

        for t in range(self.tries):
            logger.debug('%s: try %d', self.__class__.__name__, t)

            response = super(GitHubAdapter, self).send(
                request, *args, **kwargs)

            logger.debug('Got response: %d', response.status_code)

            try:
                rl_remaining = int(response.headers['X-RateLimit-Remaining'])
            except (ValueError, KeyError):
                rl_remaining = -1

            if response.status_code == 403 and rl_remaining == 0:
                rl_reset_ts = float(response.headers['X-RateLimit-Reset'])
                now_ts = time.time()

                rl_reset = datetime.datetime.utcfromtimestamp(rl_reset_ts)
                now = datetime.datetime.utcfromtimestamp(time.time())

                # There's edge situation when the rate limit is reset after the
                # response was sent by server but before we have processed it
                # then the wait_time would be negative. In this situation we
                # don't want to wait
                wait_time = max(0.0, (rl_reset - now).total_seconds())

                logger.debug('Rate limit exhausted. Will wait %ds for the '
                             'limit to reset.', wait_time)
                time.sleep(wait_time)
            else:
                return response
