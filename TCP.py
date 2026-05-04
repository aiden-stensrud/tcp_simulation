# Kahlel Cardona 904027085
# duration=64 sws=12 rws=12 error=0.05 timeout=3
#
# Usage:
#   python tcp_simulation.py duration=64 sws=12 rws=12 error=0.05 timeout=3
#
# Parameters
#   duration  : number of ticks (RTT rounds) to simulate
#   sws       : sender window size cap (max cwnd in MSS)
#   rws       : receiver window size / buffer capacity (in MSS)
#   error     : probability [0,1) that a frame or ACK is corrupted/lost
#   timeout   : ticks without progress before RTO fires
#
# Output columns
#   t       : tick (one RTT round per tick)
#   tx      : sequence number sent this tick  (- = nothing, ? = corrupted/lost)
#   event   : SS=SlowStart | CA=CongAvoid | FR=FastRecov | TO=Timeout | ZW=ZeroWin
#   cwnd    : congestion window (MSS)
#   ssth    : slow-start threshold (MSS)
#   ack_rx  : cumulative ACK received this tick (- = none, ? = corrupted)
#   rwnd    : receiver advertised free buffer (MSS)
#   eff     : effective window = min(cwnd, rwnd)
#   rcv_buf : out-of-order frames buffered at receiver

import random
import sys

MSS = 1


# ── TCP Receiver ──────────────────────────────────────────────────────────────

class TCPReceiver:
    def __init__(self, rws):
        self.rws    = rws    # total buffer capacity
        self.LFR    = -1     # last in-order frame received (frontier)
        self.buffer = []     # out-of-order frames waiting in buffer
        # IMPORTANT: rwnd is derived solely from len(self.buffer).
        # In-order frames are delivered immediately and never occupy a slot.
        # Only out-of-order frames that are parked waiting for a gap-fill
        # consume buffer space.

    @property
    def LAF(self):
        return self.LFR + self.rws

    @property
    def buf_used(self):
        """Buffer slots in use = number of out-of-order frames parked."""
        return len(self.buffer)

    @property
    def rwnd(self):
        """Free buffer space — always in [0, rws]."""
        return self.rws - self.buf_used   # buf_used <= rws always

    def receive(self, seq):
        """
        Accept seq if it is within the receive window and buffer has space.
        Returns new LFR (cumulative ACK) if the in-order frontier advanced,
        else None.
        """
        if seq <= self.LFR:        # duplicate
            return None
        if seq > self.LAF:         # outside window
            return None
        if seq != self.LFR + 1 and self.buf_used >= self.rws:
            return None            # out-of-order and buffer full

        old_LFR = self.LFR

        if seq == self.LFR + 1:
            # In-order: advance frontier, then absorb any consecutive buffered frames.
            # In-order delivery does NOT consume a buffer slot.
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
            # Out-of-order: park in buffer (costs one slot).
            if seq not in self.buffer:
                self.buffer.append(seq)
                self.buffer.sort()

        return self.LFR if self.LFR != old_LFR else None


# ── TCP Sender ────────────────────────────────────────────────────────────────

class TCPSender:
    SS, CA, FR = "SS", "CA", "FR"

    def __init__(self, sws):
        self.sws         = sws
        self.cwnd        = MSS
        self.ssthresh    = max(sws // 2, 2 * MSS)
        self.state       = self.SS
        self.LAR         = -1          # last ACK received (cumulative)
        self.LFS         = -1          # last frame sent
        self.outstanding = {}          # seq -> send_tick (unACKed frames only)
        self.dup_acks    = 0
        self.last_acked  = -1

    def effective_window(self, rwnd):
        return max(0, min(self.cwnd, rwnd, self.sws))

    def in_flight(self):
        return len(self.outstanding)

    def can_send(self, rwnd):
        return self.in_flight() < self.effective_window(rwnd)

    def send(self, tick):
        seq = self.LFS + 1
        self.LFS = seq
        self.outstanding[seq] = tick
        return seq

    def retransmit(self, seq, tick):
        if seq in self.outstanding:
            self.outstanding[seq] = tick

    def find_timed_out(self, tick, rto):
        """Return lowest-seq unACKed frame whose age >= rto, or None."""
        candidate = None
        for seq, send_tick in self.outstanding.items():
            if tick - send_tick >= rto:
                if candidate is None or seq < candidate:
                    candidate = seq
        return candidate

    def on_new_ack(self, ack):
        if ack <= self.LAR:
            return
        self.dup_acks   = 0
        self.last_acked = ack
        self.LAR        = ack
        for seq in [s for s in self.outstanding if s <= self.LAR]:
            del self.outstanding[seq]

        if self.state == self.SS:
            self.cwnd = min(self.cwnd + MSS, self.sws)
            if self.cwnd >= self.ssthresh:
                self.state = self.CA
        elif self.state == self.CA:
            self.cwnd = min(self.cwnd + max(1, (MSS * MSS) // self.cwnd), self.sws)
        elif self.state == self.FR:
            self.cwnd  = min(self.ssthresh, self.sws)
            self.state = self.CA

    def on_dup_ack(self):
        self.dup_acks += 1
        if self.state == self.FR:
            self.cwnd = min(self.cwnd + MSS, self.sws)

    def on_triple_dup_ack(self):
        self.ssthresh = max(self.cwnd // 2, 2 * MSS)
        self.cwnd     = min(self.ssthresh + 3 * MSS, self.sws)
        self.state    = self.FR
        self.dup_acks = 0

    def on_timeout(self):
        flight = self.in_flight()
        self.ssthresh = max(flight // 2, 2 * MSS)
        self.cwnd     = MSS
        self.state    = self.SS
        self.dup_acks = 0


# ── Simulation loop ───────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 6:
        print("Usage: python tcp_simulation.py "
              "duration=XXX sws=XXX rws=XXX error=X.X timeout=X")
        return

    params = {}
    for arg in sys.argv[1:]:
        k, v = arg.split('=')
        params[k] = v

    duration   = int(params['duration'])
    sws        = int(params['sws'])
    rws        = int(params['rws'])
    error_prob = float(params['error'])
    timeout    = int(params['timeout'])

    random.seed(42)

    print("Student Name: Kahlel Cardona  Student ID: 904027085")
    print("Parameters: duration={} sws={} rws={} error={} timeout={}".format(
        duration, sws, rws, error_prob, timeout))
    print()
    print("Column key:")
    print("  t       = tick (RTT round)")
    print("  tx      = frame sent  (- none, ? lost/corrupt)")
    print("  event   = SS SlowStart | CA CongAvoid | FR FastRecov "
          "| TO Timeout | ZW ZeroWin")
    print("  cwnd    = congestion window (MSS)")
    print("  ssth    = slow-start threshold (MSS)")
    print("  ack_rx  = cumulative ACK received (- none, ? corrupt)")
    print("  rwnd    = receiver free buffer (MSS)")
    print("  eff     = effective window = min(cwnd, rwnd)")
    print("  rcv_buf = out-of-order frames at receiver")
    print()
    print("{:<5} {:<6} {:<10} {:<6} {:<6} {:<7} {:<6} {:<5} {}".format(
        "t", "tx", "event", "cwnd", "ssth", "ack_rx", "rwnd", "eff", "rcv_buf"))
    print("-" * 72)

    sender        = TCPSender(sws)
    receiver      = TCPReceiver(rws)
    ack_in_flight = None   # ACK travelling back to sender (1-tick delay)

    for t in range(duration):

        # ── 1. Deliver ACK that was in the pipeline from last tick ────────
        # (Do this BEFORE sending so the sender knows its latest LAR
        #  when deciding whether it can send.)
        delivered_ack = None
        ack_str       = "-"
        if ack_in_flight is not None:
            if random.random() < error_prob:
                ack_str = "?"
            else:
                delivered_ack = ack_in_flight
                ack_str       = str(delivered_ack)

        if delivered_ack is not None:
            if delivered_ack > sender.LAR:
                sender.on_new_ack(delivered_ack)
            else:
                sender.on_dup_ack()

        # ── 2. Compute window sizes (reflect latest ACK) ──────────────────
        rwnd    = receiver.rwnd
        eff_win = sender.effective_window(rwnd)
        event   = None
        tx_str  = "-"
        tx_seq  = None

        # ── 3. Check for triple-dup-ACK → Fast Retransmit ─────────────────
        if sender.dup_acks == 3:
            sender.on_triple_dup_ack()
            event   = "FR"
            missing = sender.LAR + 1
            sender.retransmit(missing, t)
            tx_seq  = missing
            # reset dup_acks so we don't re-trigger next tick
            sender.dup_acks = 0

        # ── 4. Check for RTO ──────────────────────────────────────────────
        if event is None:
            timed_out_seq = sender.find_timed_out(t, timeout)
            if timed_out_seq is not None:
                sender.on_timeout()
                sender.retransmit(timed_out_seq, t)
                tx_seq = timed_out_seq
                event  = "TO"

        # ── 5. Zero-window probe or normal send ───────────────────────────
        if event is None:
            if rwnd == 0:
                tx_seq = sender.LAR + 1
                event  = "ZW"
            elif sender.can_send(rwnd):
                tx_seq = sender.send(t)

        # ── 6. Apply error model to outgoing data frame ───────────────────
        data_received = None
        if tx_seq is not None:
            if random.random() < error_prob:
                tx_str = "?"
            else:
                tx_str        = str(tx_seq)
                data_received = tx_seq

        # ── 7. Receiver processes frame, may generate ACK ─────────────────
        generated_ack = None
        if data_received is not None:
            generated_ack = receiver.receive(data_received)

        # ── 8. Update ACK pipeline ────────────────────────────────────────
        # If a new (advancing) ACK was generated, it goes into the pipeline.
        # Otherwise the last cumulative ACK is re-sent (TCP behaviour).
        if generated_ack is not None:
            ack_in_flight = generated_ack
        # else: ack_in_flight unchanged (last cumulative ACK stays in flight)

        # ── 9. Label event if not set ─────────────────────────────────────
        if event is None:
            event = sender.state

        # ── 10. Snapshot rwnd/eff after all updates ───────────────────────
        rwnd_now = receiver.rwnd
        eff_now  = sender.effective_window(rwnd_now)

        # ── 11. Print row ─────────────────────────────────────────────────
        buf_str = ("(" + ",".join(str(x) for x in receiver.buffer) + ")"
                   if receiver.buffer else "()")

        print("{:<5} {:<6} {:<10} {:<6} {:<6} {:<7} {:<6} {:<5} {}".format(
            t, tx_str, event,
            sender.cwnd, sender.ssthresh,
            ack_str, rwnd_now, eff_now,
            buf_str))


if __name__ == "__main__":
    main()