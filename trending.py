import requests
import re
import time
import logging
import urllib
import sys
import traceback
import redis

crypto_api = 'https://min-api.cryptocompare.com/data'
sms_api = 'https://api.clockworksms.com/http/send.aspx'
sms_key = '3270b901e913f2a0072b2bc20fe15de80cac0083'
phones = ['15102008156','19167058495']

def log_unhandled_exception(*exc_info):
   text = "".join(traceback.format_exception(*exc_info))
   logging.critical("Uncaught Exception: {0}".format(text))
   sys.exit(2)

# Gets the top 100 coins from coinmarketcap
def get_top_100():
    coins = []
    res = requests.get('https://coinmarketcap.com/')
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
    op,cl,vol,avg_vol = data['open'],data['close'],data['curr_vol'],data['avg_vol']
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
    p = ','.join(phones)
    res = requests.get('{0}?key={1}&to={2}&content={3}'.format(sms_api,sms_key,p,urllib.parse.quote_plus(s)))
    if "Error" in res.text:
        logging.warning('Error sending SMS: %s', res.text)
        return
    logging.info('SMS sent to {0}'.format(p))
    
def get_curr_price(coins):
    res = requests.get('{0}/price?fsym=BTC&tsyms={1}'.format(crypto_api,coins))                

# Configure logging
logging.basicConfig(filename='trending.log',level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
sys.excepthook = log_unhandled_exception            
            
coins = get_top_100()
coins = fix_coin_symbols(coins)

# Main loop 
tc = []
for c in coins:
    if c=='BTC':
        fsym,tsym = 'BTC','USD'
    else:
        fsym,tsym = c,'BTC'
        
    res = requests.get('{0}/histohour?fsym={1}&tsym={2}&limit=80&e=CCCAGG'.format(crypto_api,fsym,tsym)).json()
    
    if res['Response'] != 'Success':
        logging.warning('Couldn\'t find symbol %s', fsym)
        continue
    
    if not res['Data']:
        logging.error('No data returned for %s',fsym)
        continue
    
    data = summarize_data(res['Data'])
        
    if is_trending(fsym, data):
        tc.append(fsym)
        logging.info('%s is trending', fsym)            
    
    time.sleep(5)

if tc:
    notify('{0} trending'.format(','.join(tc)))
    
    