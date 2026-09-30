import os
import re
from time import time
import sys
lifeline = re.compile(r"(\d) received")
report = ("No response","Partial Response","Alive")
start=time()
for host in range(1,49):
#   ip = "129.11.146."+str(host)
   ip = "90.194.19."+str(host)
   pingaling = os.popen("ping -q -c2 "+ip,"r")
   print ("Testing ",ip,
   sys.stdout.flush())
   while 1:
      line = pingaling.readline()
      if not line: break
      igot = re.findall(lifeline,line)
      if igot:
           print (report[int(igot[0])])
stop=time()
elapsed = stop -start
print ("Time elapsed", elapsed)
print ("done.")