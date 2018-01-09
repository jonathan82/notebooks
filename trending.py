import requests
import re
import time
import logging
import urllib
import sys
import traceback
import redis
import datetime
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
import smtplib

GMAIL_USER = 'bitcoinicx'
GMAIL_PWD = 'bitcoinmania2017'
HISTORY_KEY = 'tcnotified'
HISTORY_EXP_KEY = 'tcnotified_expireAt'
CMC_API = 'https://coinmarketcap.com'
CRYPTO_API = 'https://min-api.cryptocompare.com/data'
SMS_API = 'https://api.clockworksms.com/http/send.aspx'
SMS_KEY = '3270b901e913f2a0072b2bc20fe15de80cac0083'
PHONES = ['9162438156@tmomail.net','9167058495@tmomail.net']

def requests_retry_session(
    retries=3,
    backoff_factor=0.3,
    status_forcelist=(500, 502, 504),
    session=None,
):
    session = session or requests.Session()
    retry = Retry(
        total=retries,
        read=retries,
        connect=retries,
        backoff_factor=backoff_factor,
        status_forcelist=status_forcelist,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session

def notify_email(subject, body):
    FROM = 'JonCryptoBot'
    TO = PHONES
    SUBJECT = subject
    TEXT = body

    logging.info('{0} / {1}'.format(subject, body))
    
    # Prepare actual message
    message = """From: %s\nTo: %s\nSubject: %s\n\n%s
    """ % (FROM, ", ".join(TO), SUBJECT, TEXT)
    try:
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.ehlo()
        server.starttls()
        server.login(GMAIL_USER, GMAIL_PWD)
        server.sendmail(FROM, TO, message)
        server.close()
        logging.info('Successfully sent mail to {0}'.format(','.join(TO)))
    except:
        logging.error("Failed to send mail")
        
def log_unhandled_exception(*exc_info):
   text = "".join(traceback.format_exception(*exc_info))
   logging.critical("Uncaught Exception: {0}".format(text))
   sys.exit(2)

# Gets the top 200 coins from coinmarketcap
def get_top_200():
    coins = []
    for i in range(1,3):
        res = requests_retry_session().get('{0}/{1}'.format(CMC_API, i))
        p = re.compile('<span class="currency-symbol"><a href="/currencies/.*?/">(.*?)<')
        for m in p.finditer(res.text):
            coins.append(m.group(1))
    return coins

# Gets the hi, lo, open, close and moving average from historical data
def summarize_data(data, ma_length=14, period=4):
    r = data[:-((ma_length+1)*period+1):-1] #reverse data since we're given most recent price last
    avg_vol = sum(x['volumeto'] for x in r[period:]) / ma_length
    curr_vol = sum(x['volumeto'] for x in r[:period])
    hi = max(x['high'] for x in r[:period])
    lo = min(x['low'] for x in r[:period])
    opn = r[period-1]['open']
    clo = r[0]['close'] 
    return {'hi':hi, 'lo':lo, 'avg_vol':avg_vol, 'curr_vol': curr_vol, 'open': opn, 'close': clo}

def fix_coin_symbols(coins):
    coins.remove('MIOTA')
    coins.append('IOT')
    return coins

# A coin is trending up if volume is significantly above average and spikes in price
def is_trending(sym, data, vol_threshold=3, price_threshold=1.1):    
    op,cl,vol,avg_vol,hi,lo = data['open'],data['close'],data['curr_vol'],data['avg_vol'],data['hi'],data['lo']
    if avg_vol==0:        
        logging.warning('Volume is 0 for %s', sym)
        vol,avg_vol = vol_threshold,1 # ignore volume 
    if op==0:
        logging.error('Price is 0 for %s', sym)
        return False
    if cl/op >= price_threshold and vol/avg_vol >= vol_threshold:
        return True
    return False

def notify(s):
    logging.info('SMS: '+s)
    p = ','.join(PHONES)
    res = requests_retry_session().get('{0}?key={1}&to={2}&content={3}'.format(SMS_API,SMS_KEY,p,urllib.parse.quote_plus(s)))
    if "Error" in res.text:
        logging.warning('Error sending SMS: %s', res.text)
        return
    logging.info('SMS sent to {0}'.format(p))
    
def get_curr_prices(coins):
    res = requests_retry_session().get('{0}/price?fsym=BTC&tsyms={1}'.format(CRYPTO_API,','.join(coins))).json()
    return res

# Converts decimal price in bitcoin to more readable form
def satoshi(p):
    return int(p*10**7)

# Gets the hi/lo price for coin for last n hours
def get_hilo(c, n=60):
    data = requests_retry_session().get('{0}/histohour?fsym={1}&tsym=BTC&limit={2}&e=CCCAGG'.format(CRYPTO_API,c,n)).json()
    hi = max(t['high'] for t in data)
    lo = min(t['low'] for t in data)
    return (hi,lo)

def pct_change(a, b):
    pctdiff = int(abs(a-b)/a*100)
    return '{0}{1}%'.format('+' if b>a else '-',pctdiff)

# Configure logging
logging.basicConfig(filename='trending.log',level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
sys.excepthook = log_unhandled_exception            
            
coins = get_top_200()
coins = fix_coin_symbols(coins)

rd = redis.StrictRedis(decode_responses=True)

# Main loop 
tc = []
for c in coins:
    # Skip coin if we've sent notification in last 24hrs
    if rd.hexists(HISTORY_KEY, c):
        continue
        
    if c=='BTC':
        fsym,tsym = 'BTC','USD'
    else:
        fsym,tsym = c,'BTC'        

    res = requests_retry_session().get('{0}/histohour?fsym={1}&tsym={2}&limit=80&e=CCCAGG'.format(CRYPTO_API,fsym,tsym)).json()
    
    if res['Response'] != 'Success':
        logging.warning('Couldn\'t find symbol %s', fsym)
        continue
    
    if not res['Data']:
        logging.error('No data returned for %s',fsym)
        continue
    
    data = summarize_data(res['Data'])
    
    logging.debug(data)
        
    if is_trending(fsym, data):
        tc.append(fsym)
        logging.info('%s is trending', fsym)            
    
    time.sleep(5)

if tc:
    # Get the current prices
    cp = get_curr_prices(tc)
    s = ', '.join('{0} ({1})'.format(c,satoshi(1/cp[c])) for c in tc)
    notify_email('Trending', s)
    
    # Remember coins notified already for 3 days
    now = datetime.datetime.now()
    rd.hmset(HISTORY_KEY, cp)
    rd.hmset(HISTORY_EXP_KEY, {c: now+datetime.timedelta(days=3) for c in cp})
        
# Process expired coins and calculate profits/loss
now = datetime.datetime.now()
expired = [k for k,v in rd.hgetall(HISTORY_EXP_KEY).items() if now >= datetime.datetime.strptime(v, "%Y-%m-%d %H:%M:%S.%f")]
s = ''
for c in expired:
    p = get_hilo(c)
    buy = float(rd.hget(HISTORY_KEY, c))
    if buy==0: #divide by zero
        continue
    s += '{0} ({1}/{2}), '.format(c,pct_change(buy,p[0]),pct_change(buy,p[1]))
    time.sleep(5)

if expired:
    notify_email('Profits', s)
    rd.hdel(HISTORY_KEY, *expired)    
    rd.hdel(HISTORY_EXP_KEY, *expired)