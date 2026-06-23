KeyError                                  Traceback (most recent call last)
/tmp/ipykernel_5858/3198356645.py in <cell line: 0>()
     22 TABLE    = "ad_keyword"
     23 MEDIA    = "구글"
---> 24 CUSTOMER_ID      = os.environ["GOOGLE_CUSTOMER_ID"]        # 9365791419 (법무법인KB)
     25 LOGIN_CUSTOMER   = os.environ["GOOGLE_LOGIN_CUSTOMER_ID"]  # 4715694533 (MCC)
     26 LOOKBACK_DAYS    = 3   # 어제·오늘 + 하루 더 (재집계 보정용). 어제·오늘만 원하면 2

/usr/lib/python3.12/os.py in __getitem__(self, key)

KeyError: 'GOOGLE_CUSTOMER_ID'
