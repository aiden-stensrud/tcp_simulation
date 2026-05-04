# Team Pumpkin 'Carvas
# Kahlel Cardona 904027085
# Prottasha Deb 904045750
# Aiden Stensrud 904049103

class TCPReceiver:
    def __init__(self, rws):
        self.rws    = rws    # total buffer capacity
        self.LFR    = -1     # last in-order frame received (frontier)
        self.buffer = []     # out-of-order frames waiting in buffer

    # last acknowledged frame
    @property
    def LAF(self):
        return self.LFR + self.rws

    # buffer slots used
    @property
    def buf_used(self):
        return len(self.buffer)

    # free buffer space
    @property
    def rwnd(self):
        return self.rws - self.buf_used   # buf_used <= rws always

    # accept seq if in window and there is space in the buffer and returns new ack if necessary
    def receive(self, seq):
        if seq <= self.LFR: return None # duplicate
        if seq > self.LAF: return None # outside window
        if seq != self.LFR + 1 and self.buf_used >= self.rws: return None # out of order, buffer full

        old_LFR = self.LFR

        if seq == self.LFR + 1:
            # advance frontier, then absorb any consecutive buffered frames.
            self.LFR = seq
            changed = True
            while changed:
                changed = False
                for i, s in enumerate(self.buffer):
                    if s == self.LFR + 1:
                        self.LFR += 1
                        self.buffer.pop(i)
                        # buf_used drops automatically (len shrinks)
                        changed = True
                        break
        else:
            # out-of-order: park in buffer (costs one slot).
            if seq not in self.buffer:
                self.buffer.append(seq)
                self.buffer.sort()

        return self.LFR if self.LFR != old_LFR else None
