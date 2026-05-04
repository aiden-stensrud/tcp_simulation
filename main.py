# Team Pumpkin 'Carvas
# Kahlel Cardona 904027085
# Prottasha Deb 904045750
# Aiden Stensrud 904049103

from tcp_sender import TCPSender
from tcp_receiver import TCPReceiver
import random
import sys

MSS = 1

def main():
    if len(sys.argv) != 6: raise (ValueError("Invalid number of parameters."))

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

    print("Team Pumpkin 'Carvas")
    print("Student Name: Kahlel Cardona\tStudent ID: 904027085")
    print("Student Name: Prottasha Deb\tStudent ID: 904045750")
    print("Student Name: Aiden Stensrud\tStudent ID: 904049103")
    print()
    print("Parameters: duration={} sws={} rws={} error={} timeout={}".format(
        duration, sws, rws, error_prob, timeout))
    print()
    print("{:<5} {:<6} {:<10} {:<6} {:<6} {:<7} {:<6} {:<5} {}".format(
        "t", "tx", "event", "cwnd", "ssth", "ack_rx", "rwnd", "eff", "rcv_buf"))
    print("-" * 72)

    sender = TCPSender(sws)
    receiver = TCPReceiver(rws)
    ack_in_flight = None   # ACK travelling back to sender (1-tick delay)

    for t in range(duration):
    
        # deliver ack from last tick pipeline
        delivered_ack = None
        ack_str       = "-"
        if ack_in_flight is not None:
            if random.random() < error_prob: ack_str = "?"
            else: delivered_ack, ack_str = ack_in_flight, str(delivered_ack)

        if delivered_ack is not None:
            if delivered_ack > sender.LAR: sender.on_new_ack(delivered_ack, t)
            else: sender.on_dup_ack()

        # compute window sizes to reflect the latest ACK
        rwnd    = receiver.rwnd
        eff_win = sender.effective_window(rwnd)
        event   = None
        tx_str  = "-"
        tx_seq  = None

        # check for multiple of same acknowledgements
        if sender.dup_acks == 3:
            sender.on_triple_dup_ack()
            event = "FR"
            missing = sender.LAR + 1
            sender.retransmit(missing, t)
            tx_seq = missing
            # reset dup_acks
            sender.dup_acks = 0

        # check for RTO
        if event is None:
            timed_out_seq = sender.find_timed_out(t, sender.rto)
            if timed_out_seq is not None:
                sender.on_timeout()
                sender.retransmit(timed_out_seq, t)
                tx_seq = timed_out_seq
                event  = "TO"

        # determine if zero window probe or normal send
        if event is None:
            if rwnd == 0: tx_seq, event = sender.LAR + 1, "ZW"
            elif sender.can_send(rwnd): tx_seq = sender.send(t)

        # apply error model to outgoing data frame
        data_received = None
        if tx_seq is not None:
            if random.random() < error_prob: tx_str = "?"
            else: tx_str, data_received = str(tx_seq), tx_seq

        # reciever processes frame
        generated_ack = None
        if data_received is not None: generated_ack = receiver.receive(data_received)

        # update ACK pipeline
        if generated_ack is not None: ack_in_flight = generated_ack

        # label event if not set
        if event is None: event = sender.state

        # snapshot rwnd/eff after all updates
        rwnd_now = receiver.rwnd
        eff_now  = sender.effective_window(rwnd_now)

        # print row
        buf_str = ("(" + ",".join(str(x) for x in receiver.buffer) + ")" if receiver.buffer else "()")

        print("{:<5} {:<6} {:<10} {:<6} {:<6} {:<6} {:<7} {:<6} {:<5} {}".format(
        t, tx_str, event,
        sender.cwnd, sender.ssthresh, sender.rto,
        ack_str, rwnd_now, eff_now,
        buf_str))

if __name__ == "__main__": main()
