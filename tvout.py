from machine import Timer, mem32
import framebuf
import os

try:
    from esp32 import RMT
except ImportError:
    raise RuntimeError("Platform is not ESP32!")


class TVOut(framebuf.FrameBuffer):
    # low, high
    SYNC = (0, 0)
    BLACK = (1, 0)
    WHITE = (1, 1)
    
    def __init__(self, pin_l, pin_h, chan_l=0, chan_h=1, timer=0, rmt_clock_div=8):
        self.width = 104
        self.height = 80
        
        self.buf_l = []
        self.buf_h = []
        
        platform = os.uname().machine
        if platform.count("ESP32S3"):
            RMT_REG_BASE = 0x60016000
        elif platform.count("ESP32"):
            RMT_REG_BASE = 0x3FF56000
        else:
            raise RuntimeError(f"Platform {platform} is not supported!")
        
        self.RMT_SYS_CONF_REG = RMT_REG_BASE+0xC0
        self.RMT_TX_SIM_REG = RMT_REG_BASE+0xC4
         
        self.stream_l = RMT(chan_l, pin=pin_l, clock_div=1)
        self.stream_h = RMT(chan_h, pin=pin_h, clock_div=1)
        
        # Set RMT clock divider
        mem32[self.RMT_SYS_CONF_REG] |= ((rmt_clock_div-1) << 4) | (0 << 12) | (1 << 18)
        self.rmt_step_ns = 1000000000/(RMT.source_freq()/rmt_clock_div)
        
        # simulatious mode for specified channels
        mem32[self.RMT_TX_SIM_REG] |= (1 << 4) | (1 << chan_l) | (1 << chan_h)

        bufsize = int(self.width*self.height//8)
        self.framebuffer = bytearray(bufsize)
        super().__init__(self.framebuffer, self.width, self.height, framebuf.MONO_HMSB)
        
        self.timer = Timer(timer)
        self.timer.init(freq=60, mode=Timer.PERIODIC, callback=self.output_frame_cb)
        
        self.fill(0)
        self.show()
        
        self.placeholder_buf_l = self.buf_l.copy()
        self.placeholder_buf_h = self.buf_h.copy()
    
    
    def __del__(self):
        self.timer.deinit()
        self.stream_l.wait_done(timeout=1000)
        self.stream_h.wait_done(timeout=1000)
    
    
    @micropython.native
    def from_us(self, val):
        return int(val*1000/self.rmt_step_ns)
    
    
    @micropython.native
    def show(self):
        self.buf_l.clear()
        self.buf_h.clear()
        
        levels = []
        
        levels.append((self.SYNC, 29.4))
        levels.append((self.BLACK, 34.2))
        
        for y in range(19):
            levels.append((self.BLACK, 1.5))
            levels.append((self.SYNC, 4.7))
            levels.append((self.BLACK, 57.4))
        
        for y in range(self.height*3):
            levels.append((self.BLACK, 1.5))
            levels.append((self.SYNC, 4.7))
            levels.append((self.BLACK, 4.7))
            
            # 52.655 us
            for x in range(self.width):
                pix_idx = int(x+(y//3)*self.width)
                byte_idx = int(pix_idx//8)
                bit_idx = pix_idx%8
                pixel = int(self.framebuffer[byte_idx]>>bit_idx)&1
                if pixel: level = self.WHITE
                else: level = self.BLACK
                levels.append((level, 0.5))
            levels.append((self.BLACK, 0.1))
        
        for y in range(3):
            levels.append((self.BLACK, 1.5))
            levels.append((self.SYNC, 4.7))
            levels.append((self.BLACK, 57.4))

        # Initialize current bit and timing for both streams
        current_bit_l = levels[0][0][0]
        current_timing_l = levels[0][1]
        current_bit_h = levels[0][0][1]
        current_timing_h = levels[0][1]
        
        # Process both streams in loop
        for bits, timing in levels[1:]:
            bit_l, bit_h = bits
            if bit_l == current_bit_l:
                current_timing_l += timing
            else:
                self.buf_l.append(self.from_us(current_timing_l))
                current_bit_l = bit_l
                current_timing_l = timing

            if bit_h == current_bit_h:
                current_timing_h += timing
            else:
                self.buf_h.append(self.from_us(current_timing_h))
                current_bit_h = bit_h
                current_timing_h = timing

        # Append the last timings
        self.buf_l.append(self.from_us(current_timing_l))
        self.buf_h.append(self.from_us(current_timing_h))
                
    
    @micropython.native
    def output_frame_cb(self, t):
        if len(self.buf_l) > 0 and len(self.buf_h) > 0:
            self.stream_l.write_pulses(self.buf_l, 0)
            self.stream_h.write_pulses(self.buf_h, 0)
        else:
            self.stream_l.write_pulses(self.placeholder_buf_l, 0)
            self.stream_h.write_pulses(self.placeholder_buf_h, 0)

