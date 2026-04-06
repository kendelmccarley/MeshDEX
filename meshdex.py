#!/usr/bin/env python3
"""
MeshDEX v2 - Accurate eDEX-inspired layout for Pi Zero 2 W
Layout matches reference: left panel | terminal | right panel
                          filesystem strip (bottom center)
                          keyboard (bottom right)
"""

import pygame
import os, pty, select, signal, socket, math, time, threading, collections
import psutil
from datetime import datetime
from pathlib import Path

os.environ['SDL_AUDIODRIVER'] = 'dummy'  # suppress ALSA errors

# ─── CONFIG ──────────────────────────────────────────────────────────────────
W, H    = 1366, 768  # will be overridden by actual display size
FPS     = 12
FONT    = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
FONTB   = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"

BG      = (8,   12,  16)
BG2     = (12,  20,  28)
BG3     = (6,   10,  14)
C       = (160, 220, 220)
CDM     = (60,  100, 100)
CBR     = (200, 240, 240)
CBRD    = (80,  120, 120)
CWRN    = (200, 160, 50)
CDAN    = (180, 60,  60)
CGOOD   = (60,  160, 100)

HDR_H   = 22

pygame.init()
info = pygame.display.Info()
W, H = info.current_w, info.current_h
screen = pygame.display.set_mode((W, H), pygame.FULLSCREEN | pygame.NOFRAME)
pygame.display.set_caption("MeshDEX")
pygame.mouse.set_visible(False)

# Recalculate layout for actual screen size
LEFT_W  = int(W * 0.168)
RIGHT_W = int(W * 0.176)
TERM_W  = W - LEFT_W - RIGHT_W
FS_H    = int(H * 0.286)
KB_W    = int(W * 0.527)
KB_H    = FS_H

def F(size, bold=False):
    try: return pygame.font.Font(FONTB if bold else FONT, size)
    except: return pygame.font.SysFont("monospace", size)

f7=F(9); f8=F(10); f9=F(11); f10=F(11); f11=F(12); f12=F(13)
f9b=F(11,True); f12b=F(13,True); f14b=F(15,True); f32b=F(36,True); f18=F(20)

def blit(surf, txt, font, color, x, y, anchor='tl'):
    s = font.render(str(txt), True, color)
    w2, h2 = s.get_size()
    if anchor=='tr': x-=w2
    elif anchor=='tc': x-=w2//2
    elif anchor=='c': x-=w2//2; y-=h2//2
    surf.blit(s, (x, y))
    return w2

def hrule(surf, x, y, w, color=None):
    pygame.draw.line(surf, color or CBRD, (x,y), (x+w,y), 1)

def vrule(surf, x, y, h, color=None):
    pygame.draw.line(surf, color or CBRD, (x,y), (x,y+h), 1)

def bar(surf, x, y, w, h, pct, color=None):
    pygame.draw.rect(surf, (20,35,40), pygame.Rect(x,y,w,h))
    fw = int(w * min(pct,100)/100)
    if fw>0:
        c = color or (CDAN if pct>90 else CWRN if pct>70 else C)
        pygame.draw.rect(surf, c, pygame.Rect(x,y,fw,h))

def fmt(b):
    if b>=1e9: return f"{b/1e9:.1f}G"
    if b>=1e6: return f"{b/1e6:.1f}M"
    if b>=1e3: return f"{b/1e3:.0f}K"
    return f"{int(b)}B"

def uptime_str(s):
    d=s//86400; h=(s%86400)//3600; m=(s%3600)//60
    if d: return f"{d}d {h:02d}:{m:02d}"
    return f"{h:02d}:{m:02d}:{s%60:02d}"

def draw_wave(surf, rect, data, color, scale=None):
    pts = list(data)
    if not pts: return
    mx = scale or max(max(pts),1)
    w2 = rect.w / max(len(pts),1)
    drawn = []
    for i,v in enumerate(pts):
        x = rect.x + int(i*w2)
        y = rect.bottom - int((v/mx)*rect.h)
        y = max(rect.y, min(rect.bottom, y))
        drawn.append((x,y))
    if len(drawn)>1:
        pygame.draw.lines(surf, color, False, drawn, 1)

# ─── STATS ───────────────────────────────────────────────────────────────────
class Stats:
    HIST=60
    # Globe location — used for weather fetch too
    LAT=32.2; LON=-110.9; TZ='America/Phoenix'

    def __init__(self):
        self.cpu=0.0; self.temp=0.0; self.freq=0
        self.mem_pct=0.0; self.mem_used=0; self.mem_total=0
        self.swap_pct=0.0; self.disk_pct=0.0
        self.disk_used=0; self.disk_total=0
        self.uptime=0; self.hostname=socket.gethostname()
        self.procs=[]; self.ifaces={}
        self.net_sent=0; self.net_recv=0
        self.cpu_hist=collections.deque([0]*self.HIST,self.HIST)
        self.net_up=collections.deque([0]*self.HIST,self.HIST)
        self.net_dn=collections.deque([0]*self.HIST,self.HIST)
        self._ps=0; self._pr=0
        # Weather data
        self.wx_temp=None; self.wx_wind_spd=None
        self.wx_wind_dir=None; self.wx_wind_dir_str='--'
        self.wx_sunrise='--:--'; self.wx_sunset='--:--'
        self.wx_updated=0
        self._lock=threading.Lock(); self._run=True
        psutil.cpu_percent()
        threading.Thread(target=self._loop,daemon=True).start()
        threading.Thread(target=self._wx_loop,daemon=True).start()

    def _loop(self):
        while self._run:
            try: self._update()
            except: pass
            time.sleep(3)

    def _wx_loop(self):
        """Fetch weather from Open-Meteo every 10 minutes"""
        while self._run:
            try: self._fetch_weather()
            except: pass
            time.sleep(600)

    def _fetch_weather(self):
        import urllib.request, json
        url=(f'https://api.open-meteo.com/v1/forecast'
             f'?latitude={self.LAT}&longitude={self.LON}'
             f'&current=temperature_2m,wind_speed_10m,wind_direction_10m'
             f'&daily=sunrise,sunset'
             f'&temperature_unit=fahrenheit&wind_speed_unit=mph'
             f'&timezone={self.TZ}&forecast_days=1')
        with urllib.request.urlopen(url,timeout=10) as r:
            d=json.loads(r.read())
        cur=d.get('current',{})
        daily=d.get('daily',{})
        temp=cur.get('temperature_2m')
        wspd=cur.get('wind_speed_10m')
        wdir=cur.get('wind_direction_10m')
        # Convert degrees to compass
        dirs=['N','NNE','NE','ENE','E','ESE','SE','SSE',
              'S','SSW','SW','WSW','W','WNW','NW','NNW']
        compass=dirs[int((wdir+11.25)/22.5)%16] if wdir is not None else '--'
        # Parse sunrise/sunset HH:MM from ISO string
        def hhmm(s):
            try: return s[11:16]
            except: return '--:--'
        sunrise=hhmm(daily.get('sunrise',[''])[0])
        sunset =hhmm(daily.get('sunset', [''])[0])
        with self._lock:
            self.wx_temp=temp; self.wx_wind_spd=wspd
            self.wx_wind_dir=wdir; self.wx_wind_dir_str=compass
            self.wx_sunrise=sunrise; self.wx_sunset=sunset
            self.wx_updated=int(time.time())

    def _update(self):
        cpu=psutil.cpu_percent()
        mem=psutil.virtual_memory(); swap=psutil.swap_memory()
        disk=psutil.disk_usage('/'); net=psutil.net_io_counters()
        temp=0.0
        try:
            with open('/sys/class/thermal/thermal_zone0/temp') as f:
                temp=int(f.read())/1000
        except: pass
        freq=0
        try: fr=psutil.cpu_freq(); freq=int(fr.current) if fr else 0
        except: pass
        procs=[]
        for p in sorted(psutil.process_iter(['pid','name','cpu_percent','memory_percent']),
                        key=lambda x:x.info['cpu_percent'] or 0,reverse=True)[:10]:
            try: procs.append({'pid':p.info['pid'],'name':(p.info['name'] or '')[:16],
                               'cpu':p.info['cpu_percent'] or 0,'mem':p.info['memory_percent'] or 0})
            except: pass
        ifaces={}
        for iface,addrs in psutil.net_if_addrs().items():
            if iface=='lo': continue
            for addr in addrs:
                if addr.family==socket.AF_INET:
                    st=psutil.net_if_stats().get(iface)
                    ifaces[iface]={'ip':addr.address,'up':st.isup if st else False}
        sd=net.bytes_sent-self._ps; rd=net.bytes_recv-self._pr
        self._ps=net.bytes_sent; self._pr=net.bytes_recv
        with self._lock:
            self.cpu=cpu; self.temp=temp; self.freq=freq
            self.mem_pct=mem.percent; self.mem_used=mem.used; self.mem_total=mem.total
            self.swap_pct=swap.percent; self.disk_pct=disk.percent
            self.disk_used=disk.used; self.disk_total=disk.total
            self.uptime=int(time.time()-psutil.boot_time())
            self.procs=procs; self.ifaces=ifaces
            self.net_sent=net.bytes_sent; self.net_recv=net.bytes_recv
            self.cpu_hist.append(cpu)
            self.net_up.append(sd/3); self.net_dn.append(rd/3)

    def get(self):
        with self._lock:
            return {k:v for k,v in self.__dict__.items()
                    if not k.startswith('_')}

# ─── TERMINAL ────────────────────────────────────────────────────────────────
import pyte

class Terminal:
    def __init__(self,cols=80,rows=24):
        self.cols=cols; self.rows=rows
        self._screen=pyte.Screen(cols,rows)
        self._stream=pyte.ByteStream(self._screen)
        self._lock=threading.Lock()
        self._master=None; self._pid=None; self._run=False

    def start(self,cmd='/bin/bash'):
        import struct,fcntl,termios
        master,slave=pty.openpty()
        env=os.environ.copy()
        env.update({'TERM':'xterm-256color','COLUMNS':str(self.cols),'LINES':str(self.rows),
                    'TERM_PROGRAM':'meshdex'})
        pid=os.fork()
        if pid==0:
            os.setsid(); os.close(master)
            for fd in (0,1,2): os.dup2(slave,fd)
            if slave>2: os.close(slave)
            fcntl.ioctl(0,termios.TIOCSCTTY,1)
            fcntl.ioctl(0,termios.TIOCSWINSZ,struct.pack('HHHH',self.rows,self.cols,0,0))
            os.execvpe(cmd,[cmd],env); os._exit(1)
        os.close(slave); self._master=master; self._pid=pid; self._run=True
        threading.Thread(target=self._read,daemon=True).start()

    def _read(self):
        while self._run:
            try:
                r,_,_=select.select([self._master],[],[],0.05)
                if r:
                    data=os.read(self._master,8192)
                    if data:
                        with self._lock:
                            self._stream.feed(data)
            except OSError: break

    def write(self,s):
        if self._master:
            try: os.write(self._master,s.encode())
            except: pass

    def get_screen(self):
        # pyte color constants
        ANSI_COLORS={
            'black':(0,0,0),'red':(170,0,0),'green':(0,170,0),
            'brown':(170,85,0),'blue':(0,0,170),'magenta':(170,0,170),
            'cyan':(0,170,170),'white':(170,170,170),
            'brightblack':(85,85,85),'brightred':(255,85,85),
            'brightgreen':(85,255,85),'brightyellow':(255,255,85),
            'brightblue':(85,85,255),'brightmagenta':(255,85,255),
            'brightcyan':(85,255,255),'brightwhite':(255,255,255),
        }
        def parse_color(col,default):
            if col=='default': return default
            if isinstance(col,int):
                # 256-color
                if col<16:
                    names=list(ANSI_COLORS.keys())
                    return ANSI_COLORS.get(names[col],default)
                if col<232:
                    col-=16; b=col%6; g=(col//6)%6; r=col//36
                    return (r*51,g*51,b*51)
                v=(col-232)*10+8; return (v,v,v)
            if isinstance(col,str) and col in ANSI_COLORS:
                return ANSI_COLORS[col]
            return default

        with self._lock:
            buf=[]
            for y in range(self._screen.lines):
                row=[]
                for x in range(self._screen.columns):
                    char=self._screen.buffer[y][x]
                    ch=char.data if char.data else ' '
                    # Resolve colors
                    fg=parse_color(char.fg,C)
                    bg=parse_color(char.bg,BG3)
                    # Bold brightens fg
                    if char.bold and isinstance(char.fg,str) and char.fg!='default':
                        fg=parse_color('bright'+char.fg,fg)
                    # Reverse video
                    if char.reverse: fg,bg=bg,fg
                    row.append((ch,fg,bg))
                buf.append(row)
            cx=self._screen.cursor.x
            cy=self._screen.cursor.y
            return buf,cx,cy

    def stop(self):
        self._run=False
        if self._pid:
            try: os.kill(self._pid,signal.SIGTERM)
            except: pass

# ─── FILESYSTEM ──────────────────────────────────────────────────────────────
class FS:
    def __init__(self):
        self.path=str(Path.home()); self.entries=[]; self.scroll=0; self._load()

    def _load(self):
        try:
            e=[]
            if str(Path(self.path).parent)!=self.path:
                e.append(('..', True, 0))
            for item in sorted(os.scandir(self.path),key=lambda x:(not x.is_dir(),x.name.lower())):
                if not item.name.startswith('.'):
                    try: sz=item.stat().st_size
                    except: sz=0
                    e.append((item.name,item.is_dir(),sz))
            self.entries=e[:80]
        except: self.entries=[('..', True, 0)]

    def go(self,name):
        if name=='..': self.path=str(Path(self.path).parent)
        else:
            p=os.path.join(self.path,name)
            if os.path.isdir(p): self.path=p
        self.scroll=0; self._load()

# ─── GLOBE ───────────────────────────────────────────────────────────────────
class Globe:
    COASTS=[
        # North America - West Coast
        [(71,-156),(70,-148),(68,-166),(66,-168),(64,-163),(60,-166),
         (58,-152),(57,-135),(54,-130),(49,-124),(46,-124),(42,-124),
         (38,-122),(37,-122),(34,-120),(32,-117),(28,-115),(22,-106),(18,-103)],
        # North America - East Coast
        [(47,-53),(47,-54),(46,-60),(44,-66),(43,-70),(42,-70),(41,-71),
         (40,-74),(38,-75),(36,-76),(35,-76),(33,-79),(30,-81),(28,-80),
         (25,-80),(24,-81),(24,-82),(25,-80)],
        # Gulf Coast
        [(25,-80),(26,-80),(28,-82),(29,-85),(30,-88),(29,-90),(29,-93),
         (28,-96),(26,-97),(24,-110),(20,-105),(18,-103)],
        # Great Lakes outline (simplified)
        [(47,-84),(46,-82),(42,-82),(42,-80),(43,-79),(44,-76),(45,-76),(47,-84)],
        # Alaska
        [(71,-156),(68,-166),(64,-168),(60,-166),(58,-152),(57,-135),(60,-141),(63,-141),(66,-141),(68,-141),(71,-156)],
        # Canada East
        [(47,-53),(50,-55),(52,-55),(53,-57),(52,-66),(50,-66),(48,-69),(47,-53)],
        # Greenland
        [(60,-46),(62,-42),(64,-40),(66,-38),(68,-32),(70,-26),(72,-22),
         (74,-20),(76,-18),(78,-18),(80,-18),(82,-22),(83,-30),(83,-38),
         (82,-44),(80,-52),(78,-58),(76,-64),(74,-68),(72,-68),(70,-54),
         (68,-52),(66,-52),(64,-50),(62,-48),(60,-46)],
        # South America - West Coast
        [(12,-72),(8,-77),(5,-77),(0,-80),(-5,-81),(-8,-78),(-10,-75),
         (-15,-75),(-18,-72),(-22,-70),(-28,-70),(-33,-71),(-38,-73),
         (-42,-74),(-46,-74),(-50,-74),(-54,-68),(-56,-68)],
        # South America - East Coast
        [(12,-72),(10,-63),(8,-62),(5,-52),(2,-50),(0,-50),(-5,-35),
         (-8,-34),(-10,-36),(-15,-39),(-20,-40),(-23,-43),(-28,-48),
         (-33,-53),(-38,-58),(-42,-62),(-46,-65),(-50,-68),(-54,-65),(-56,-68)],
        # Caribbean (simplified)
        [(18,-73),(18,-72),(20,-74),(22,-75),(23,-82),(23,-80),(18,-66),(18,-73)],
        # Europe - West
        [(71,28),(70,25),(69,18),(68,14),(65,14),(63,8),(60,5),(58,5),
         (56,8),(55,8),(53,8),(52,4),(51,2),(50,2),(48,-5),(47,-2),
         (44,-9),(43,-9),(42,-9),(40,-8),(38,-9),(37,-9),(36,-6),(35,-6)],
        # Scandinavia detail
        [(58,5),(59,5),(60,5),(61,6),(62,6),(63,8),(64,11),(65,14),
         (66,14),(67,15),(68,14),(69,18),(70,20),(71,28),(70,30),
         (68,28),(66,24),(64,20),(62,20),(60,18),(58,18),(57,12),(58,5)],
        # British Isles
        [(50,-5),(51,-4),(52,-5),(53,-4),(54,-3),(55,-2),(56,-3),
         (57,-2),(58,-3),(58,-5),(57,-6),(55,-5),(53,-4)],
        [(51,0),(52,0),(53,0),(54,0),(55,0),(55,-1),(54,-3),(53,-4),(51,0)],
        # Iberian Peninsula detail
        [(36,-6),(36,-7),(37,-9),(38,-9),(40,-8),(42,-9),(43,-9),
         (44,-2),(43,3),(42,3),(41,2),(40,0),(38,0),(37,-1),(36,-5),(36,-6)],
        # Italy
        [(44,8),(44,12),(42,14),(40,16),(38,16),(37,15),(38,13),(40,14),(42,12),(44,8)],
        # Greece
        [(42,22),(40,22),(38,24),(37,22),(37,24),(38,26),(40,24),(42,22)],
        # Africa - West Coast
        [(35,-6),(33,-8),(30,-10),(28,-13),(25,-15),(20,-17),(15,-17),
         (10,-17),(5,-5),(0,-8),(-2,8),(-5,10),(-5,12),(-5,14),
         (-10,13),(-15,12),(-18,12),(-22,14),(-25,15),(-28,16),(-34,18)],
        # Africa - East Coast
        [(-34,18),(-30,30),(-25,33),(-20,35),(-15,40),(-10,40),(-5,40),
         (0,41),(5,42),(10,42),(11,43),(12,44),(15,42),(20,37),(25,37),
         (30,32),(32,32),(35,36),(37,36)],
        # Africa - North Coast
        [(35,-6),(36,-2),(36,2),(36,6),(37,10),(37,13),(33,13),(32,20),
         (31,25),(30,30),(28,32),(22,37),(20,37)],
        # Middle East
        [(37,36),(36,36),(33,35),(30,34),(29,34),(26,37),(24,38),(20,39),
         (15,42),(12,44),(10,45),(8,45),(10,50),(22,60),(24,58),(26,57)],
        # Arabian Peninsula
        [(30,48),(28,48),(24,52),(22,58),(20,58),(16,52),(12,44),(15,42),(20,39),(24,38),(26,37),(30,34),(30,48)],
        # India
        [(25,68),(22,68),(20,73),(18,73),(16,73),(12,77),(8,77),
         (8,80),(10,80),(12,80),(15,80),(18,84),(20,86),(22,88),
         (24,88),(26,88),(25,68)],
        # Southeast Asia mainland
        [(22,100),(20,100),(18,100),(16,100),(14,100),(12,101),(10,104),
         (5,103),(1,104),(3,100),(5,100),(8,98),(10,99),(12,100),(14,100)],
        # Malay Peninsula + Indonesia (simplified)
        [(5,103),(1,104),(0,110),(-5,105),(-8,115),(-8,125),(-5,120),(0,110)],
        # China/Korea coast
        [(22,114),(25,119),(28,121),(30,122),(32,121),(34,119),(36,120),
         (38,120),(40,122),(42,120),(38,126),(36,129),(34,129),(32,130)],
        # Japan
        [(30,130),(31,130),(33,130),(34,132),(35,136),(35,137),(36,137),
         (37,137),(38,139),(39,140),(40,141),(41,141),(42,141),(43,141),
         (44,145),(43,141),(41,141),(40,141)],
        [(33,130),(34,130),(35,130),(36,136),(35,137)],
        # Australia
        [(-14,126),(-16,123),(-18,122),(-20,118),(-22,114),(-25,113),
         (-28,114),(-32,116),(-34,119),(-34,122),(-35,136),(-36,140),
         (-38,140),(-38,146),(-38,148),(-36,150),(-34,151),(-30,153),
         (-26,153),(-22,150),(-18,146),(-15,145),(-12,136),(-12,130),(-14,126)],
        # New Zealand (simplified)
        [(-34,172),(-36,175),(-38,176),(-40,176),(-42,172),(-46,168),(-44,170),(-40,172),(-36,174),(-34,172)],
        # Philippines (simplified)
        [(18,122),(16,120),(12,122),(10,124),(8,126),(10,125),(14,121),(18,122)],
        # Taiwan
        [(25,122),(24,122),(22,121),(22,120),(24,121),(25,122)],
        # Sri Lanka
        [(8,80),(7,80),(6,80),(7,81),(8,81),(8,80)],
        # Madagascar
        [(-12,49),(-15,50),(-18,44),(-20,44),(-22,44),(-25,47),(-25,50),(-20,48),(-15,50),(-12,49)],
        # Iceland
        [(63,-20),(65,-14),(66,-14),(66,-18),(65,-22),(64,-24),(63,-22),(63,-20)],
    ]
    def __init__(self): self.rot=0.0; self.lat=Stats.LAT; self.lon=Stats.LON

    def proj(self,lat,lon,cx,cy,r):
        phi=math.radians(90-lat); theta=math.radians(lon+self.rot)
        x=r*math.sin(phi)*math.cos(theta); y=r*math.cos(phi)
        z=r*math.sin(phi)*math.sin(theta)
        return int(cx+x),int(cy-y),z>0

    def update(self): self.rot=(self.rot-0.5)%360

    def draw(self,surf,cx,cy,r):
        pygame.draw.circle(surf,(4,12,18),(cx,cy),r)
        pygame.draw.circle(surf,CBRD,(cx,cy),r,1)
        for lat in range(-60,61,30):
            pts=[]
            for lon in range(-180,181,6):
                x,y,v=self.proj(lat,lon,cx,cy,r)
                if v: pts.append((x,y))
                elif pts:
                    if len(pts)>1: pygame.draw.lines(surf,(20,50,55),False,pts,1)
                    pts=[]
            if len(pts)>1: pygame.draw.lines(surf,(20,50,55),False,pts,1)
        for lon in range(0,360,30):
            pts=[]
            for lat2 in range(-90,91,6):
                x,y,v=self.proj(lat2,lon,cx,cy,r)
                if v: pts.append((x,y))
                elif pts:
                    if len(pts)>1: pygame.draw.lines(surf,(20,50,55),False,pts,1)
                    pts=[]
            if len(pts)>1: pygame.draw.lines(surf,(20,50,55),False,pts,1)
        for coast in self.COASTS:
            pts=[]
            for lat3,lon3 in coast:
                x,y,v=self.proj(lat3,lon3,cx,cy,r)
                if v: pts.append((x,y))
                elif pts:
                    if len(pts)>1: pygame.draw.lines(surf,CDM,False,pts,2)
                    pts=[]
            if len(pts)>1: pygame.draw.lines(surf,CDM,False,pts,2)
        x,y,v=self.proj(self.lat,self.lon,cx,cy,r)
        if v:
            p=int(2+2*abs(math.sin(time.time()*2)))
            pygame.draw.circle(surf,CWRN,(x,y),p+2)
            pygame.draw.circle(surf,CWRN,(x,y),2)

# ─── KEYBOARD ────────────────────────────────────────────────────────────────
# Laptop keyboard layout matching standard diagram
# Each entry: (primary_label, shift_label, width_units, pygame_key)
# All rows total 15 units wide except fn row (14) and bottom row (15)
ROWS=[
    # Row 0 — Function row, shorter height, all 1u
    [('esc','',1,pygame.K_ESCAPE),
     ('F1','',1,pygame.K_F1),('F2','',1,pygame.K_F2),
     ('F3','',1,pygame.K_F3),('F4','',1,pygame.K_F4),
     ('F5','',1,pygame.K_F5),('F6','',1,pygame.K_F6),
     ('F7','',1,pygame.K_F7),('F8','',1,pygame.K_F8),
     ('F9','',1,pygame.K_F9),('F10','',1,pygame.K_F10),
     ('F11','',1,pygame.K_F11),('F12','',1,pygame.K_F12),
     ('del','',1,pygame.K_DELETE)],
    # Row 1 — Number row, backspace=2u
    [('`','~',1,pygame.K_BACKQUOTE),
     ('1','!',1,pygame.K_1),('2','@',1,pygame.K_2),
     ('3','#',1,pygame.K_3),('4','$',1,pygame.K_4),
     ('5','%',1,pygame.K_5),('6','^',1,pygame.K_6),
     ('7','&',1,pygame.K_7),('8','*',1,pygame.K_8),
     ('9','(',1,pygame.K_9),('0',')',1,pygame.K_0),
     ('-','_',1,pygame.K_MINUS),('=','+',1,pygame.K_EQUALS),
     ('delete','',2,pygame.K_BACKSPACE)],
    # Row 2 — QWERTY, tab=1.5u, backslash=1.5u
    [('tab','',1.5,pygame.K_TAB),
     ('Q','',1,pygame.K_q),('W','',1,pygame.K_w),
     ('E','',1,pygame.K_e),('R','',1,pygame.K_r),
     ('T','',1,pygame.K_t),('Y','',1,pygame.K_y),
     ('U','',1,pygame.K_u),('I','',1,pygame.K_i),
     ('O','',1,pygame.K_o),('P','',1,pygame.K_p),
     ('[','{',1,pygame.K_LEFTBRACKET),(']','}',1,pygame.K_RIGHTBRACKET),
     ('\\','|',1.5,pygame.K_BACKSLASH)],
    # Row 3 — Home row, caps=1.75u, return=2.25u
    [('caps','',1.75,pygame.K_CAPSLOCK),
     ('A','',1,pygame.K_a),('S','',1,pygame.K_s),
     ('D','',1,pygame.K_d),('F','',1,pygame.K_f),
     ('G','',1,pygame.K_g),('H','',1,pygame.K_h),
     ('J','',1,pygame.K_j),('K','',1,pygame.K_k),
     ('L','',1,pygame.K_l),(';',':',1,pygame.K_SEMICOLON),
     ("'",'"',1,pygame.K_QUOTE),
     ('return','',2.25,pygame.K_RETURN)],
    # Row 4 — Shift row: lshift=2.25u, rshift=1.75u, ↑=1u (right of rshift)
    [('shift','',2.25,pygame.K_LSHIFT),
     ('Z','',1,pygame.K_z),('X','',1,pygame.K_x),
     ('C','',1,pygame.K_c),('V','',1,pygame.K_v),
     ('B','',1,pygame.K_b),('N','',1,pygame.K_n),
     ('M','',1,pygame.K_m),(',','<',1,pygame.K_COMMA),
     ('.','> ',1,pygame.K_PERIOD),('/','?',1,pygame.K_SLASH),
     ('shift','',1.75,pygame.K_RSHIFT),
     ('↑','',1,pygame.K_UP)],
    # Row 5 — Bottom row: fn ctrl opt cmd [space] cmd opt ← ↓ →
    [('fn','',1.25,None),('ctrl','',1.25,pygame.K_LCTRL),
     ('opt','',1.25,pygame.K_LALT),('⌘','',1.5,pygame.K_LGUI),
     ('','',5.5,pygame.K_SPACE),
     ('⌘','',1.25,pygame.K_RGUI),('opt','',1,pygame.K_RALT),
     ('←','',1,pygame.K_LEFT),('↓','',1,pygame.K_DOWN),('→','',1,pygame.K_RIGHT)],
]

# Font for keyboard rendering
_kb_font_main = None   # set in Keyboard.__init__
_kb_font_shift = None
_kb_font_fn = None

class Keyboard:
    def __init__(self,x,y,w,h):
        global _kb_font_main, _kb_font_shift, _kb_font_fn
        self.active=set(); self.keys=[]
        self.x=x; self.y=y; self.w=w; self.h=h

        # Font sizes for key labels
        _kb_font_main  = F(11, bold=True)   # primary char — large, bold
        _kb_font_shift = F(8)               # shift char — small, top-left
        _kb_font_fn    = F(9)               # function key labels

        # Row heights — fn row is shorter
        fn_h   = int(h * 0.13)   # ESC/F-key row
        main_h = int((h - fn_h - 14) / 5)  # remaining 5 rows
        gap    = 3

        total_h = fn_h + 5*main_h + 6*gap
        start_y = y + (h - total_h) // 2

        unit = w / 15.0  # all main rows are 15 units wide
        row_heights = [fn_h] + [main_h]*5

        ky = start_y
        for row_i, (row, rh) in enumerate(zip(ROWS, row_heights)):
            kx = x + 4
            is_fn_row = (row_i == 0)
            for label,shift,width,pk in row:
                kw = unit * width - gap
                rect = pygame.Rect(int(kx), int(ky), max(1,int(kw)), int(rh))
                self.keys.append((rect, label, shift, pk, is_fn_row))
                kx += unit * width
            ky += rh + gap

    def press(self,k): self.active.add(k)
    def release(self,k): self.active.discard(k)

    def draw(self,surf):
        for rect,label,shift,pk,is_fn in self.keys:
            on = pk in self.active if pk else False

            # Colors
            if on:
                bg = C; border = C; fg_main = BG; fg_shift = BG
            else:
                bg = BG2; border = CBRD; fg_main = C; fg_shift = CDM

            # Key background with rounded corners
            pygame.draw.rect(surf, bg, rect, border_radius=3)

            # Border glow — brighter on sides/bottom for depth effect
            pygame.draw.rect(surf, border, rect, 1, border_radius=3)
            if not on:
                # Subtle highlight on top edge
                pygame.draw.line(surf, (100,160,160),
                                 (rect.x+3, rect.y+1), (rect.right-3, rect.y+1))
                # Darker shadow on bottom edge
                pygame.draw.line(surf, (20,40,50),
                                 (rect.x+3, rect.bottom-2), (rect.right-3, rect.bottom-2))

            # Draw shift character — top left, small
            if shift and not is_fn:
                ss = _kb_font_shift.render(shift, True, fg_shift)
                surf.blit(ss, (rect.x+4, rect.y+2))

            # Draw primary label — centered
            font = _kb_font_fn if is_fn or len(label)>2 else _kb_font_main
            if label == '':
                # Spacebar — draw a thin line instead
                sy = rect.centery
                pygame.draw.line(surf, border,
                                 (rect.x+8, sy), (rect.right-8, sy), 1)
            else:
                ls = font.render(label, True, fg_main)
                lx = rect.centerx - ls.get_width()//2
                ly = rect.centery - ls.get_height()//2
                # If has shift char, nudge label down slightly
                if shift and not is_fn:
                    ly += 3
                surf.blit(ls, (lx, ly))

# ─── MAIN ────────────────────────────────────────────────────────────────────
def main():
    clock=pygame.time.Clock()
    pygame.key.set_repeat(400,40)

    # Fixed 80x24 terminal - font size 18 verified to fit on this display
    # cw=11 ch=21: 80*11=880px wide, 24*21=504px tall fits in 885x519 pane
    TERM_COLS = 80
    TERM_ROWS = 24
    # Use 90% of pane width/height, centered, to guarantee no bleed
    term_pane_w = TERM_W - 4
    term_pane_h = H - FS_H - HDR_H - 4
    term_render_w = int(term_pane_w * 0.90)
    term_render_h = int(term_pane_h * 0.90)
    # Find largest font that fits in the reduced area
    term_font_size = 8
    for size in range(8, 32):
        f = pygame.font.Font(FONT, size)
        if f.size('M')[0] * TERM_COLS <= term_render_w and \
           f.get_linesize() * TERM_ROWS <= term_render_h:
            term_font_size = size
        else:
            break
    term_font = pygame.font.Font(FONT, term_font_size)
    term_char_w = term_font.size('M')[0]
    term_char_h = term_font.get_linesize()
    # Offsets to center the render within the pane
    term_offset_x = (term_pane_w - term_char_w * TERM_COLS) // 2
    term_offset_y = (term_pane_h - term_char_h * TERM_ROWS) // 2
    print(f"Terminal geometry: font={term_font_size}pt cw={term_char_w} ch={term_char_h}")
    print(f"  pane={term_pane_w}x{term_pane_h} content={term_char_w*TERM_COLS}x{term_char_h*TERM_ROWS}")
    print(f"  offset=({term_offset_x},{term_offset_y}) right_margin={term_pane_w - term_char_w*TERM_COLS - term_offset_x}")
    stats=Stats()

    # 5 independent terminal instances
    NUM_TABS = 5
    terms = [Terminal(cols=TERM_COLS, rows=TERM_ROWS) for _ in range(NUM_TABS)]
    tab_names = ['MAIN SHELL', 'EMPTY', 'EMPTY', 'EMPTY', 'EMPTY']
    tab_rects = []  # populated during rendering for click detection
    active_tab = 0
    for t in terms:
        t.start()

    # Auto-launch MeshTTY in tab 0 if available
    meshtty_launch = os.path.expanduser('~/MeshTTY/launch-pi.sh')
    if os.path.exists(meshtty_launch):
        tab_names[0] = 'MESHTTY'
        def _autolaunch():
            time.sleep(1.5)
            terms[0].write('cd ~/MeshTTY && bash launch-pi.sh\n')
        threading.Thread(target=_autolaunch, daemon=True).start()

    # Convenience reference to active terminal
    def term():
        return terms[active_tab]

    fs=FS(); globe=Globe()
    kb_x=W-KB_W
    kb=Keyboard(kb_x, H-FS_H, KB_W, FS_H)

    scan=pygame.Surface((W,H),pygame.SRCALPHA)
    for yy in range(0,H,3):
        pygame.draw.line(scan,(0,0,0,12),(0,yy),(W,yy))

    input_buf=''; frame=0; running=True
    tab_rects=[]  # populated each frame for click detection

    while running:
        for ev in pygame.event.get():
            if ev.type==pygame.QUIT: running=False
            elif ev.type==pygame.MOUSEBUTTONDOWN:
                if ev.button==1:
                    mx,my=ev.pos
                    # Click on tab bar
                    if my < HDR_H:
                        for i,(rect,name) in enumerate(tab_rects):
                            if rect.collidepoint(mx,my):
                                active_tab=i
                                input_buf=''
                                break
                    # Filesystem scroll
                    elif my>H-FS_H and mx<W-KB_W:
                        pass
            elif ev.type==pygame.KEYDOWN:
                kb.press(ev.key)
                if ev.key==pygame.K_RETURN:
                    term().write('\n')
                    input_buf=''
                elif ev.key==pygame.K_q and (ev.mod&(pygame.KMOD_ALT|pygame.KMOD_LALT|pygame.KMOD_RALT)):
                    running=False
                elif ev.key==pygame.K_t and (ev.mod&(pygame.KMOD_ALT|pygame.KMOD_LALT|pygame.KMOD_RALT)):
                    # Alt+T cycles to next tab
                    active_tab=(active_tab+1)%NUM_TABS
                    input_buf=''
                elif ev.key==pygame.K_s and (ev.mod&(pygame.KMOD_ALT|pygame.KMOD_LALT|pygame.KMOD_RALT)):
                    ts=datetime.now().strftime('%Y%m%d_%H%M%S')
                    path=os.path.expanduser(f'~/meshdex_screenshot_{ts}.png')
                    pygame.image.save(screen, path)
                    print(f'Screenshot saved: {path}')
                    pygame.time.wait(1000)
                    pygame.event.clear()
                elif ev.key==pygame.K_BACKSPACE:
                    if input_buf: input_buf=input_buf[:-1]
                    term().write('\x7f')
                elif ev.key==pygame.K_TAB:
                    if ev.mod&pygame.KMOD_SHIFT: term().write('\x1b[Z')
                    else: term().write('\t')
                elif ev.key==pygame.K_ESCAPE: term().write('\x1b')
                elif ev.key==pygame.K_UP: term().write('\x1b[A')
                elif ev.key==pygame.K_DOWN: term().write('\x1b[B')
                elif ev.key==pygame.K_LEFT: term().write('\x1b[D')
                elif ev.key==pygame.K_RIGHT: term().write('\x1b[C')
                elif ev.key==pygame.K_PAGEUP: term().write('\x1b[5~')
                elif ev.key==pygame.K_PAGEDOWN: term().write('\x1b[6~')
                elif ev.key==pygame.K_HOME: term().write('\x1b[H')
                elif ev.key==pygame.K_END: term().write('\x1b[F')
                elif ev.key==pygame.K_DELETE: term().write('\x1b[3~')
                elif ev.key==pygame.K_F1: term().write('\x1bOP')
                elif ev.key==pygame.K_F2: term().write('\x1bOQ')
                elif ev.key==pygame.K_F3: term().write('\x1bOR')
                elif ev.key==pygame.K_F4: term().write('\x1bOS')
                elif ev.key==pygame.K_F5: term().write('\x1b[15~')
                elif ev.key==pygame.K_F6: term().write('\x1b[17~')
                elif ev.key==pygame.K_F7: term().write('\x1b[18~')
                elif ev.key==pygame.K_F8: term().write('\x1b[19~')
                elif ev.key==pygame.K_F9: term().write('\x1b[20~')
                elif ev.key==pygame.K_F10: term().write('\x1b[21~')
                elif ev.key==pygame.K_F11: term().write('\x1b[23~')
                elif ev.key==pygame.K_F12: term().write('\x1b[24~')
                elif ev.mod&pygame.KMOD_CTRL:
                    if pygame.K_a<=ev.key<=pygame.K_z:
                        term().write(chr(ev.key-pygame.K_a+1))
                    elif ev.key==pygame.K_LEFTBRACKET: term().write('\x1b')
                    elif ev.key==pygame.K_BACKSLASH: term().write('\x1c')
                    elif ev.key==pygame.K_RIGHTBRACKET: term().write('\x1d')
                elif ev.unicode and ord(ev.unicode)>=32:
                    input_buf+=ev.unicode
                    term().write(ev.unicode)
            elif ev.type==pygame.KEYUP: kb.release(ev.key)
            elif ev.type==pygame.MOUSEWHEEL:
                mx,my=pygame.mouse.get_pos()
                if my>H-FS_H and mx<W-KB_W:
                    fs.scroll=max(0,fs.scroll-ev.y)

        frame+=1; globe.update()
        s=stats.get(); now=datetime.now()
        screen.fill(BG)

        # Dividers - terminal dividers only go to filesystem top, not full height
        vrule(screen,LEFT_W,0,H-FS_H); vrule(screen,LEFT_W+TERM_W,0,H-FS_H)
        hrule(screen,0,H-FS_H,W-KB_W)        # filesystem top border
        hrule(screen,W-KB_W,H-FS_H,KB_W)     # keyboard top border (same as filesystem)
        vrule(screen,W-KB_W,H-FS_H,FS_H)     # between filesystem and keyboard

        # ══ LEFT PANEL ══════════════════════════════════════════════════
        lx=0; ly=0; lw=LEFT_W

        pygame.draw.rect(screen,BG2,pygame.Rect(0,0,lw,HDR_H))
        hrule(screen,0,HDR_H,lw)
        blit(screen,"PANEL",f9b,C,8,5)
        blit(screen,"SYSTEM",f9b,CDM,lw-8,5,'tr')
        ly=HDR_H+8

        # Clock
        blit(screen,now.strftime("%H:%M:%S"),f32b,C,lw//2,ly,'tc')
        ly+=40

        # Date row
        blit(screen,now.strftime("%Y"),f9,CDM,8,ly)
        uptime=s.get('uptime',0)
        blit(screen,f"UP {uptime_str(uptime)}",f9,C,lw//2,ly,'tc')
        blit(screen,now.strftime("%b %d"),f9,CDM,lw-8,ly,'tr')
        ly+=14

        # Info grid 2x2
        grid=[("TYPE","linux"),("POWER","DC"),("MODEL",s.get('hostname','')[:8].upper()),("OS","debian")]
        for i,(k,v) in enumerate(grid):
            gx=8+(i%2)*(lw//2-4); gy=ly+(i//2)*20
            blit(screen,k,f8,CDM,gx,gy); blit(screen,v,f9b,C,gx,gy+10)
        ly+=44

        hrule(screen,0,ly,lw); ly+=4

        # CPU usage header
        blit(screen,"CPU USAGE",f8,CDM,8,ly)
        blit(screen,s.get('hostname','').upper(),f8,C,lw-8,ly,'tr')
        ly+=12

        # CPU waveform #1
        wh=36; wr=pygame.Rect(4,ly,lw-8,wh)
        pygame.draw.rect(screen,BG3,wr)
        cpu_hist=s.get('cpu_hist',collections.deque([0]*60))
        draw_wave(screen,wr,cpu_hist,C,100)
        cpu=s.get('cpu',0)
        blit(screen,f"Avg. {cpu:.0f}%",f8,C,8,ly+wh+2)
        ly+=wh+16

        # CPU waveform #2 (dimmed, simulates second core group)
        wr2=pygame.Rect(4,ly,lw-8,wh)
        pygame.draw.rect(screen,BG3,wr2)
        draw_wave(screen,wr2,cpu_hist,CDM,100)
        blit(screen,f"Avg. {cpu:.0f}%",f8,CDM,8,ly+wh+2)
        ly+=wh+16

        # Temp/freq/tasks row
        freq=s.get('freq',0); temp=s.get('temp',0)
        for lbl,val,col2 in [
            ("TEMP",f"{temp:.0f}°C",CDAN if temp>75 else CWRN if temp>65 else C),
            ("MIN",f"{freq//1000:.1f}G",C),
            ("MAX",f"{freq//1000:.1f}G",C),
            ("TASKS",str(len(s.get('procs',[]))),C)]:
            xi=8+["TEMP","MIN","MAX","TASKS"].index(lbl)*52
            blit(screen,lbl,f8,CDM,xi,ly)
            blit(screen,val,f9b,col2,xi,ly+10)
        ly+=26

        hrule(screen,0,ly,lw); ly+=4

        # Memory
        mem_pct=s.get('mem_pct',0); mem_used=s.get('mem_used',0); mem_total=s.get('mem_total',0)
        blit(screen,"MEMORY",f8,CDM,8,ly)
        blit(screen,f"USING {fmt(mem_used)} OUT OF {fmt(mem_total)}",f8,C,lw-8,ly,'tr')
        ly+=12

        dot_cols=20; dot_rows=4; dot_w=(lw-16)//dot_cols
        filled=int(mem_pct/100*dot_cols*dot_rows)
        for row in range(dot_rows):
            for col in range(dot_cols):
                idx=row*dot_cols+col
                dx=8+col*dot_w; dy=ly+row*8
                color=C if idx<filled else (20,45,50)
                pygame.draw.rect(screen,color,pygame.Rect(dx,dy,dot_w-1,5))
        ly+=dot_rows*8+4

        blit(screen,"SWAP",f8,CDM,8,ly)
        swap_pct=s.get('swap_pct',0)
        blit(screen,f"{swap_pct:.1f}%",f8,C,lw-8,ly,'tr')
        ly+=10
        bar(screen,8,ly,lw-16,4,swap_pct); ly+=10

        hrule(screen,0,ly,lw); ly+=4

        # Top processes
        blit(screen,"TOP PROCESSES",f8,CDM,8,ly)
        blit(screen,"PID | NAME | CPU | MEM",f7,CDM,lw-8,ly,'tr')
        ly+=12
        for p in s.get('procs',[])[:8]:
            if ly+13>H-4: break
            blit(screen,str(p['pid']),f8,CDM,8,ly)
            blit(screen,p['name'][:12],f8,C,50,ly)
            blit(screen,f"{p['cpu']:.1f}%",f8,CDAN if p['cpu']>50 else C,158,ly)
            blit(screen,f"{p['mem']:.1f}%",f8,CDM,lw-8,ly,'tr')
            ly+=13

        # ══ TERMINAL ════════════════════════════════════════════════════
        tx=LEFT_W; tw=TERM_W; tbot=H-FS_H

        pygame.draw.rect(screen,BG2,pygame.Rect(tx,0,tw,HDR_H))
        hrule(screen,tx,HDR_H,tw)
        blit(screen,"TERMINAL",f9b,C,tx+8,5)

        # Tabs
        tab_rects=[]
        tab_x=tx+80
        for i,tab in enumerate(tab_names):
            tw2=f9.size(tab)[0]+20
            tab_rect=pygame.Rect(tab_x,0,tw2,HDR_H)
            tab_rects.append((tab_rect, tab))
            if i==active_tab:
                pygame.draw.rect(screen,BG3,tab_rect)
                hrule(screen,tab_x,HDR_H,tw2,C)
                blit(screen,tab,f9b,C,tab_x+10,5)
            else:
                pygame.draw.rect(screen,BG2,tab_rect)
                blit(screen,tab,f9,CDM,tab_x+10,5)
            vrule(screen,tab_x+tw2,0,HDR_H)
            tab_x+=tw2
        blit(screen,tab_names[active_tab],f9b,CDM,tx+tw-8,5,'tr')

        # Terminal output - centered in pane with margins
        term_start_x = tx + 2 + term_offset_x
        term_start_y = HDR_H + 2 + term_offset_y
        exact_w = TERM_COLS * term_char_w
        exact_h = TERM_ROWS * term_char_h
        term_inner = pygame.Rect(tx+2, HDR_H+2, tw-4, tbot-HDR_H-4)
        term_content = pygame.Rect(term_start_x, term_start_y, exact_w, exact_h)
        pygame.draw.rect(screen, BG3, term_inner)
        scr,cur_x,cur_y=term().get_screen()
        blink_on=(frame//6)%2==0
        for row_i,row in enumerate(scr):
            ly3=term_start_y+row_i*term_char_h
            if ly3+term_char_h>term_content.bottom: break
            cx=term_start_x
            for col_i,cell in enumerate(row):
                ch,fg,bg=cell if len(cell)==3 else (cell[0],cell[1],BG3)
                # Ensure colors are valid RGB tuples
                if not isinstance(fg,tuple): fg=C
                if not isinstance(bg,tuple): bg=BG3
                is_cursor=(row_i==cur_y and col_i==cur_x and blink_on)
                char_rect=pygame.Rect(cx,ly3,term_char_w,term_char_h)
                # Clip to this exact cell so wide glyphs can't bleed right
                screen.set_clip(char_rect)
                draw_bg=fg if is_cursor else bg
                if draw_bg!=BG3:
                    pygame.draw.rect(screen,draw_bg,char_rect)
                draw_fg=bg if is_cursor else fg
                safe_ch=ch if (ch and ch.strip() and ch.isprintable()) else ' '
                if not safe_ch: safe_ch=' '
                ts=term_font.render(safe_ch,True,draw_fg if draw_fg else C)
                screen.blit(ts,(cx,ly3))
                cx+=term_char_w

        screen.set_clip(None)  # remove clip
        blit(screen,now.strftime("%a. %d %b %Y %H:%M:%S"),f8,CDM,tx+tw-8,tbot-16,'tr')

        # ══ FILESYSTEM ══════════════════════════════════════════════════
        fsx=0; fsy=H-FS_H; fsw=W-KB_W  # from left edge to keyboard

        pygame.draw.rect(screen,BG2,pygame.Rect(fsx,fsy,fsw,HDR_H))
        hrule(screen,fsx,fsy+HDR_H,fsw)
        blit(screen,"FILESYSTEM",f9b,C,fsx+8,fsy+5)
        pd=fs.path; pd=('...'+pd[-44:]) if len(pd)>47 else pd
        blit(screen,pd,f9,CDM,fsx+fsw//2,fsy+5,'tc')
        blit(screen,f"Mount / used {s.get('disk_pct',0):.0f}%",f8,CDM,fsx+8,fsy+FS_H-14)
        bar(screen,fsx+8,fsy+FS_H-6,fsw-16,3,s.get('disk_pct',0))

        # File icon grid
        fy2=fsy+HDR_H+6; col_w=85; rows_max=2
        cols=(fsw-16)//col_w
        shown=fs.entries[fs.scroll:]
        for i,(name,is_dir,size) in enumerate(shown):
            col=i%cols; row=i//cols
            if row>=rows_max: break
            ix=fsx+8+col*col_w; iy2=fy2+row*88
            # Icon box
            ir=pygame.Rect(ix,iy2,44,38)
            pygame.draw.rect(screen,BG3,ir,border_radius=3)
            pygame.draw.rect(screen,CBRD,ir,1,border_radius=3)
            if is_dir:
                # Folder icon - tab shape
                pygame.draw.rect(screen,CDM,pygame.Rect(ix+6,iy2+14,32,18),border_radius=2)
                pygame.draw.rect(screen,CDM,pygame.Rect(ix+6,iy2+10,14,6),border_radius=2)
                pygame.draw.rect(screen,BG3,pygame.Rect(ix+8,iy2+16,28,14),border_radius=1)
            else:
                # File icon - page with folded corner
                pygame.draw.rect(screen,CBRD,pygame.Rect(ix+10,iy2+8,22,26),border_radius=1)
                pygame.draw.polygon(screen,BG3,[(ix+24,iy2+8),(ix+32,iy2+8),(ix+32,iy2+16)])
                pygame.draw.line(screen,BG2,(ix+24,iy2+8),(ix+32,iy2+16),1)
                pygame.draw.line(screen,BG3,(ix+12,iy2+18),(ix+28,iy2+18),1)
                pygame.draw.line(screen,BG3,(ix+12,iy2+22),(ix+28,iy2+22),1)
                pygame.draw.line(screen,BG3,(ix+12,iy2+26),(ix+22,iy2+26),1)
            # Name
            dn=name[:10]+'..' if len(name)>12 else name
            s3=f7.render(dn,True,C if is_dir else CDM)
            screen.blit(s3,(ix+22-s3.get_width()//2,iy2+42))

        # ══ RIGHT PANEL ══════════════════════════════════════════════════
        rx=LEFT_W+TERM_W; ry=0; rw=RIGHT_W

        pygame.draw.rect(screen,BG2,pygame.Rect(rx,0,rw,HDR_H))
        hrule(screen,rx,HDR_H,rw)
        blit(screen,"PANEL",f9b,CDM,rx+8,5)
        blit(screen,"NETWORK",f9b,C,rx+rw-8,5,'tr')
        ry=HDR_H+6

        # Network status
        ifaces=s.get('ifaces',{})
        first=next(iter(ifaces.items()),(None,{}))
        iname,iinfo=first
        blit(screen,"NETWORK STATUS",f8,CDM,rx+8,ry)
        if iname: blit(screen,f"Interface: {iname}",f8,C,rx+rw-8,ry,'tr')
        ry+=14
        blit(screen,"STATE",f8,CDM,rx+8,ry)
        blit(screen,"IPv4",f8,CDM,rx+75,ry)
        blit(screen,"PING",f8,CDM,rx+165,ry)
        ry+=10
        sc=CGOOD if iinfo.get('up') else CDAN
        blit(screen,"ONLINE" if iinfo.get('up') else "OFFLINE",f9b,sc,rx+8,ry)
        blit(screen,iinfo.get('ip','--'),f8,C,rx+75,ry)
        blit(screen,"--ms",f8,CDM,rx+165,ry)
        ry+=18; hrule(screen,rx,ry,rw); ry+=6

        # Globe
        blit(screen,"WORLD VIEW",f8,CDM,rx+8,ry)
        blit(screen,"GLOBAL NETWORK MAP",f7,CDM,rx+rw-8,ry,'tr')
        ry+=12
        blit(screen,"ENDPOINT LAT/LON",f7,CDM,rx+8,ry)
        blit(screen,"32.2°N 110.9°W",f7,C,rx+rw-8,ry,'tr')
        ry+=6
        gr=min(rw//2-6,90)
        gcx=rx+rw//2; gcy=ry+gr+4
        globe.draw(screen,gcx,gcy,gr)
        ry+=gr*2+12; hrule(screen,rx,ry,rw); ry+=6

        # Weather
        blit(screen,"WEATHER",f8,CDM,rx+8,ry)
        wx_age=int(time.time())-s.get('wx_updated',0)
        age_str=f"~{wx_age//60}m ago" if wx_age<3600 and s.get('wx_updated') else "fetching..."
        blit(screen,age_str,f7,CDM,rx+rw-8,ry,'tr')
        ry+=14

        wx_temp=s.get('wx_temp')
        wx_spd=s.get('wx_wind_spd')
        wx_dir=s.get('wx_wind_dir_str','--')
        wx_rise=s.get('wx_sunrise','--:--')
        wx_set=s.get('wx_sunset','--:--')

        # Temperature — large
        temp_str=f"{wx_temp:.0f}°F" if wx_temp is not None else '--°F'
        blit(screen,temp_str,f9b,C,rx+rw//2,ry,'tc')
        ry+=16

        # Wind
        wind_str=f"{wx_spd:.0f} mph" if wx_spd is not None else '-- mph'
        blit(screen,"WIND",f7,CDM,rx+8,ry)
        blit(screen,f"{wx_dir}  {wind_str}",f8,C,rx+rw-8,ry,'tr')
        ry+=14

        hrule(screen,rx,ry,rw); ry+=6

        # Sunrise / Sunset
        blit(screen,"SUNRISE",f7,CDM,rx+8,ry)
        blit(screen,"SUNSET",f7,CDM,rx+rw-8,ry,'tr')
        ry+=10
        blit(screen,f"↑ {wx_rise}",f9b,CWRN,rx+8,ry)
        blit(screen,f"{wx_set} ↓",f9b,CDM,rx+rw-8,ry,'tr')
        ry+=16; hrule(screen,rx,ry,rw); ry+=6

        # Network traffic graph
        blit(screen,"NETWORK TRAFFIC",f8,CDM,rx+8,ry)
        blit(screen,"UP / DOWN, MB/S",f7,CDM,rx+rw-8,ry,'tr')
        ry+=12
        blit(screen,"TOTAL",f7,CDM,rx+8,ry)
        blit(screen,f"{fmt(s.get('net_sent',0))} OUT, {fmt(s.get('net_recv',0))} IN",
             f7,C,rx+rw-8,ry,'tr')
        ry+=10
        gh=60; gr2=pygame.Rect(rx+4,ry,rw-8,gh)
        pygame.draw.rect(screen,BG3,gr2)
        pygame.draw.rect(screen,CBRD,gr2,1)
        mid=ry+gh//2; hrule(screen,rx+4,mid,rw-8,(30,60,60))
        up_h=s.get('net_up',collections.deque([0]*60))
        dn_h=s.get('net_dn',collections.deque([0]*60))
        mx=max(max(up_h,default=1),max(dn_h,default=1),1)
        draw_wave(screen,pygame.Rect(rx+4,ry,rw-8,gh//2),up_h,C,mx)
        draw_wave(screen,pygame.Rect(rx+4,mid,rw-8,gh//2),dn_h,CDM,mx)
        blit(screen,f"{fmt(mx)}/s",f7,CDM,rx+6,ry+2)
        ry+=gh+6

        # Extra ifaces
        for in2,ii2 in list(ifaces.items())[:2]:
            dot=CGOOD if ii2['up'] else CDAN
            pygame.draw.circle(screen,dot,(rx+10,ry+6),4)
            blit(screen,in2,f8,C,rx+20,ry+1)
            blit(screen,ii2.get('ip',''),f7,CDM,rx+20,ry+12)
            ry+=22

        # ══ KEYBOARD ════════════════════════════════════════════════════
        pygame.draw.rect(screen,BG2,pygame.Rect(kb_x,H-FS_H,KB_W,FS_H))
        kb.draw(screen)

        # Scanlines
        screen.blit(scan,(0,0))
        pygame.display.flip()
        clock.tick(FPS)

    for t in terms: t.stop()
    stats._run=False; pygame.quit()

if __name__=='__main__':
    main()
