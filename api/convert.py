import re
import json
import urllib.parse
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler

AMAZON_INDIA_DOMAIN = "amazon.in"

ASIN_REGEX = re.compile(
    r'(?:dp|gp/product|gp/aw/d|product|ASIN)/([A-Z0-9]{10})',
    re.IGNORECASE
)
FALLBACK_ASIN_REGEX = re.compile(
    r'[/?&](?:asin=)?([B0-9][A-Z0-9]{9})(?:[/?&]|$)',
    re.IGNORECASE
)
BARE_ASIN_REGEX = re.compile(
    r'\b([B0-9][A-Z0-9]{9})\b',
    re.IGNORECASE
)
ANY_URL_REGEX = re.compile(
    r'https?://[^\s<>"\']+',
    re.IGNORECASE
)


class RedirectCapture(urllib.request.HTTPRedirectHandler):
    def __init__(self):
        self.locations = []

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.locations.append(newurl)
        if ASIN_REGEX.search(newurl) or FALLBACK_ASIN_REGEX.search(newurl):
            return None
        return urllib.request.Request(newurl, headers=req.headers)


def extract_url_from_text(text: str) -> str:
    match = ANY_URL_REGEX.search(text)
    if match:
        return match.group(0).rstrip('.,;)]}')
    return text.strip()


def extract_asin(text_or_url: str):
    if not text_or_url:
        return None
    match = ASIN_REGEX.search(text_or_url)
    if match:
        return match.group(1).upper()
    fallback = FALLBACK_ASIN_REGEX.search(text_or_url)
    if fallback:
        return fallback.group(1).upper()
    clean = text_or_url.strip()
    if len(clean) == 10 and BARE_ASIN_REGEX.match(clean):
        return clean.upper()
    return None


def unshorten_url(url: str, timeout: int = 8) -> str:
    clean_url = extract_url_from_text(url)
    if extract_asin(clean_url):
        return clean_url

    headers = {
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/122.0.0.0 Safari/537.36'
        ),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
    }

    req = urllib.request.Request(clean_url, headers=headers)
    handler = RedirectCapture()
    opener = urllib.request.build_opener(handler)

    try:
        with opener.open(req, timeout=timeout) as response:
            final_url = response.geturl()
            handler.locations.append(final_url)
            return final_url
    except urllib.error.HTTPError as e:
        if 'Location' in e.headers:
            loc = e.headers['Location']
            handler.locations.append(loc)
            return loc
    except Exception:
        pass

    for loc in reversed(handler.locations):
        if extract_asin(loc):
            return loc

    return clean_url


def convert_to_affiliate_link(raw_input: str, tag: str, subtag: str = None) -> dict:
    clean_input = raw_input.strip()
    if not clean_input:
        return {'success': False, 'error': 'Empty input.'}

    extracted_url = extract_url_from_text(clean_input)
    asin = extract_asin(extracted_url)
    resolved_url = extracted_url

    if not asin:
        resolved_url = unshorten_url(extracted_url)
        asin = extract_asin(resolved_url)

    if not asin:
        return {
            'success': False,
            'error': 'Could not detect an Amazon product ASIN in the link or text.'
        }

    params = {'tag': tag}
    if subtag:
        params['ascsubtag'] = subtag

    query_str = urllib.parse.urlencode(params)
    affiliate_url = f"https://www.{AMAZON_INDIA_DOMAIN}/dp/{asin}?{query_str}"

    return {
        'success': True,
        'affiliate_url': affiliate_url,
        'asin': asin,
        'domain': AMAZON_INDIA_DOMAIN,
        'original_url': extracted_url,
        'resolved_url': resolved_url
    }


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_POST(self):
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            data = json.loads(body)

            raw_input = data.get('url', '').strip()
            tag = data.get('tag', 'yourtag-21').strip()
            subtag = data.get('subtag', 'website')

            if not raw_input:
                response_data = {'success': False, 'error': 'No URL provided.'}
            elif not tag:
                response_data = {'success': False, 'error': 'Affiliate tag is required.'}
            else:
                response_data = convert_to_affiliate_link(raw_input, tag=tag, subtag=subtag)

        except json.JSONDecodeError:
            response_data = {'success': False, 'error': 'Invalid JSON body.'}
        except Exception as e:
            response_data = {'success': False, 'error': str(e)}

        response_bytes = json.dumps(response_data).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Content-Length', str(len(response_bytes)))
        self.end_headers()
        self.wfile.write(response_bytes)
