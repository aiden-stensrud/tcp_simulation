# Team Pumpkin 'Carvas
# Kahlel Cardona 904027085
# Prottasha Deb 904045750
# Aiden Stensrud 904049103

MSS = 1

class TCPSender:
    SS, CA, FR = "SS", "CA", "FR"

    # initialize tcp sender
    def __init__(self, sws):
        self.sws         = sws
        self.cwnd        = MSS
        self.ssthresh    = max(sws // 2, 2 * MSS)
        self.state       = self.SS
        self.LAR         = -1
        self.LFS         = -1
        self.outstanding = {}
        self.dup_acks    = 0
        self.last_acked  = -1
        self.estimated_rtt = 3.0
        self.dev_rtt = 1.0
        self.rto = self.estimated_rtt + 4 * self.dev_rtt
        self.retransmitted = set()

    # compute effective send window
    def effective_window(self, rwnd):
        return max(0, min(self.cwnd, rwnd, self.sws))

    # get num. of unacknowledged packets
    def in_flight(self):
        return len(self.outstanding)

    # check if sender can transmit more data
    def can_send(self, rwnd):
        return self.in_flight() < self.effective_window(rwnd)

    # send a new packet
    def send(self, tick):
        seq = self.LFS + 1
        self.LFS = seq
        self.outstanding[seq] = tick
        return seq

    # retransmit a specific packet
    def retransmit(self, seq, tick):
        if seq in self.outstanding:
            self.outstanding[seq] = tick
            self.retransmitted.add(seq)

    # find the earliet timed-out packet
    def find_timed_out(self, tick, rto):
        candidate = None
        for seq, send_tick in self.outstanding.items():
            if tick - send_tick >= rto:
                if candidate is None or seq < candidate:
                    candidate = seq
        return candidate

    # handle a new cumulative ACK
    def on_new_ack(self, ack, tick):
        if ack <= self.LAR:
            return

        self.update_rtt(ack, tick)

        self.dup_acks = 0
        self.last_acked = ack
        self.LAR = ack

        for seq in [s for s in self.outstanding if s <= self.LAR]:
            del self.outstanding[seq]
            self.retransmitted.discard(seq)

        if self.state == self.SS:
            self.cwnd = min(self.cwnd + MSS, self.sws)
            if self.cwnd >= self.ssthresh:
                self.state = self.CA
        elif self.state == self.CA:
            self.cwnd = min(self.cwnd + max(1, (MSS * MSS) // self.cwnd), self.sws)
        elif self.state == self.FR:
            self.cwnd = min(self.ssthresh, self.sws)
            self.state = self.CA

    # handle a duplicate ACK
    def on_dup_ack(self):
        self.dup_acks += 1
        if self.state == self.FR:
            self.cwnd = min(self.cwnd + MSS, self.sws)

    # handle 3x duplicate acknowledgements
    def on_triple_dup_ack(self):
        self.ssthresh = max(self.cwnd // 2, 2 * MSS)
        self.cwnd     = min(self.ssthresh + 3 * MSS, self.sws)
        self.state    = self.FR
        self.dup_acks = 0

    # handle retransmission timeout
    def on_timeout(self):
        flight = self.in_flight()
        self.ssthresh = max(flight // 2, 2 * MSS)
        self.cwnd     = MSS
        self.state    = self.SS
        self.dup_acks = 0
   
   # use Karn's Algorithm to update rtt
    def update_rtt(self, ack, tick):
        acked_seqs = [s for s in self.outstanding if s <= ack]

        valid_samples = [
            tick - self.outstanding[s]
            for s in acked_seqs
            if s not in self.retransmitted
        ]

        if not valid_samples:
            return

        sample_rtt = max(valid_samples)

        self.estimated_rtt = 0.875 * self.estimated_rtt + 0.125 * sample_rtt
        self.dev_rtt = 0.75 * self.dev_rtt + 0.25 * abs(sample_rtt - self.estimated_rtt)
        self.rto = max(1, int(round(self.estimated_rtt + 4 * self.dev_rtt)))
