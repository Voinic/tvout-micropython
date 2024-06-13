from machine import Timer, mem32
import framebuf

try:
    from esp32 import RMT
except ImportError:
    raise RuntimeError("Platform is not supported!")

class TVOut(framebuf.FrameBuffer):
    RMT_TX_SIM_REG = const(0x600160C4)  #esp32 s3
    #RMT_TX_SIM_REG = const(0x3FF560C4)  #esp32

    # low, high
    SYNC = (0, 0)
    BLACK = (1, 0)
    WHITE = (1, 1)

    WIDTH = 104
    HEIGHT = 80

    def __init__(self, pin_l, pin_h, chan_l=0, chan_h=1):
        rmt_source_freq = RMT.source_freq()
        rmt_clock_div = 8
        self.rmt_step_ns = 1000000000//(rmt_source_freq//rmt_clock_div)
        
        self.sync_reg_bits = 0x10 | (chan_l+1) | (chan_h+1)
        
        self.stream_l = RMT(chan_l, pin=pin_l, clock_div=rmt_clock_div)
        self.stream_h = RMT(chan_h, pin=pin_h, clock_div=rmt_clock_div)
        
        self.buf_l = []
        self.buf_h = []
        
        bufsize = int(self.WIDTH*self.HEIGHT//8)
        self.framebuffer = bytearray(bufsize)
        super().__init__(self.framebuffer, self.WIDTH, self.HEIGHT, framebuf.MONO_HMSB)
    
    def from_us(self, val):
        return int(val*1000//self.rmt_step_ns)
    
    def to_us(self, val):
        return val*self.rmt_step_ns/1000

    def sumarize(self):
        timings_sum_l = 0
        timings_sum_h = 0
        for timing in self.buf_l:
            timings_sum_l += timing
        for timing in self.buf_h:
            timings_sum_h += timing
        return self.to_us(timings_sum_l), self.to_us(timings_sum_h)
    
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
        
        for y in range(self.HEIGHT*3):
            levels.append((self.BLACK, 1.5))
            levels.append((self.SYNC, 4.7))
            levels.append((self.BLACK, 4.7))
            
            #52.655
            for x in range(self.WIDTH):
                pix_idx = int(x+(y//3)*self.WIDTH)
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
        
        #print(f"start bit low: {current_bit_l}, start bit high: {current_bit_h}")

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

        period_l, period_h = self.sumarize()
        #print(f"period low: {period_l}, period high: {period_h}")
        

    def output_frame_cb(self, t):
        if len(self.buf_l) > 0 and len(self.buf_h) > 0:
            mem32[self.RMT_TX_SIM_REG] = self.sync_reg_bits
            self.stream_l.write_pulses(self.buf_l, 0)
            self.stream_h.write_pulses(self.buf_h, 0)
    
    def begin(self, timer=0):
        self.timer = Timer(timer)
        self.timer.init(freq=60, mode=Timer.PERIODIC, callback=self.output_frame_cb)
    
    def end(self):
        self.timer.deinit()
        self.stream_l.wait_done(timeout=1000)
        self.stream_h.wait_done(timeout=1000)
        del self.timer
        
