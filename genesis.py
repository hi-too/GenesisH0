#!/usr/bin/env python3
import hashlib
import binascii
import struct
import os
import time
import sys
import optparse
import scrypt

# Note: This code uses Construct 2.x. If you have Construct 3 the API may differ.
from construct import Struct, Byte, Bytes, StaticField, UBInt32

def main():
    options = get_args()
    algorithm = get_algorithm(options)
    
    input_script  = create_input_script(options.timestamp)
    output_script = create_output_script(options.pubkey)
    # hash merkle root is the double sha256 hash of the transaction(s) 
    tx = create_transaction(input_script, output_script, options)
    hash_merkle_root = hashlib.sha256(hashlib.sha256(tx).digest()).digest()
    print_block_info(options, hash_merkle_root)
    
    block_header = create_block_header(hash_merkle_root, options.time, options.bits, options.nonce)
    genesis_hash, nonce = generate_hash(block_header, algorithm, options.nonce, options.bits)
    announce_found_genesis(genesis_hash, nonce)

def get_args():
    parser = optparse.OptionParser()
    parser.add_option("-t", "--time", dest="time", default=int(time.time()), 
                      type="int", help="the (unix) time when the genesisblock is created")
    parser.add_option("-z", "--timestamp", dest="timestamp", 
                      default="The Times 03/Jan/2009 Chancellor on brink of second bailout for banks",
                      type="str", help="the pszTimestamp found in the coinbase of the genesisblock")
    parser.add_option("-n", "--nonce", dest="nonce", default=0,
                      type="int", help="the first value of the nonce that will be incremented when searching the genesis hash")
    parser.add_option("-a", "--algorithm", dest="algorithm", default="SHA256",
                      help="the PoW algorithm: [SHA256|scrypt|X11|X13|X15]")
    parser.add_option("-p", "--pubkey", dest="pubkey", 
                      default="04678afdb0fe5548271967f1a67130b7105cd6a828e03909a67962e0ea1f61deb649f6bc3f4cef38c4f35504e51ec112de5c384df7ba0b8d578a4c702b6bf11d5f",
                      type="str", help="the pubkey found in the output script")
    parser.add_option("-v", "--value", dest="value", default=5000000000,
                      type="int", help="the value in coins for the output, full value (e.g. in bitcoin 5000000000 – to get other coins value: Block Value * 100000000)")
    parser.add_option("-b", "--bits", dest="bits",
                      type="int", help="the target in compact representation, associated to a difficulty of 1")
    
    (options, args) = parser.parse_args()
    if not options.bits:
        if options.algorithm in ["scrypt", "X11", "X13", "X15"]:
            options.bits = 0x1e0ffff0
        else:
            options.bits = 0x1d00ffff
    return options

def get_algorithm(options):
    supported_algorithms = ["SHA256", "scrypt", "X11", "X13", "X15"]
    if options.algorithm in supported_algorithms:
        return options.algorithm
    else:
        sys.exit("Error: Given algorithm must be one of: " + str(supported_algorithms))

def create_input_script(psz_timestamp):
    psz_prefix = ""
    # use OP_PUSHDATA1 if required
    if len(psz_timestamp) > 76:
        psz_prefix = '4c'
    # In Python 3, use format strings instead of .encode('hex')
    length_hex = '{:02x}'.format(len(psz_timestamp))
    script_prefix = '04ffff001d0104' + psz_prefix + length_hex
    timestamp_hex = psz_timestamp.encode('utf-8').hex()
    full_script_hex = script_prefix + timestamp_hex
    print(full_script_hex)
    return bytes.fromhex(full_script_hex)

def create_output_script(pubkey):
    script_len = '41'
    OP_CHECKSIG = 'ac'
    return bytes.fromhex(script_len + pubkey + OP_CHECKSIG)

def create_transaction(input_script, output_script, options):
    # Construct the transaction using Construct.
    # Note: The following structure is based on the original code and may need adjustment
    # if you are using a different version of Construct.
    transaction = Struct("transaction",
        Bytes("version", 4),
        Byte("num_inputs"),
        StaticField("prev_output", 32),
        UBInt32("prev_out_idx"),
        Byte("input_script_len"),
        Bytes("input_script", len(input_script)),
        UBInt32("sequence"),
        Byte("num_outputs"),
        Bytes("out_value", 8),
        Byte("output_script_len"),
        Bytes("output_script",  0x43),
        UBInt32("locktime")
    )
    
    # Parse a dummy transaction of the correct length
    dummy_length = 127 + len(input_script)
    tx = transaction.parse(b'\x00' * dummy_length)
    tx.version           = struct.pack("<I", 1)
    tx.num_inputs        = 1
    tx.prev_output       = struct.pack("<qqqq", 0, 0, 0, 0)
    tx.prev_out_idx      = 0xFFFFFFFF
    tx.input_script_len  = len(input_script)
    tx.input_script      = input_script
    tx.sequence          = 0xFFFFFFFF
    tx.num_outputs       = 1
    tx.out_value         = struct.pack("<q", options.value)
    tx.output_script_len = 0x43
    tx.output_script     = output_script
    tx.locktime          = 0 
    return transaction.build(tx)

def create_block_header(hash_merkle_root, time_value, bits, nonce):
    block_header = Struct("block_header",
        Bytes("version", 4),
        Bytes("hash_prev_block", 32),
        Bytes("hash_merkle_root", 32),
        Bytes("time", 4),
        Bytes("bits", 4),
        Bytes("nonce", 4)
    )
    
    genesisblock = block_header.parse(b'\x00' * 80)
    genesisblock.version          = struct.pack("<I", 1)
    genesisblock.hash_prev_block  = struct.pack("<qqqq", 0, 0, 0, 0)
    genesisblock.hash_merkle_root = hash_merkle_root
    genesisblock.time             = struct.pack("<I", time_value)
    genesisblock.bits             = struct.pack("<I", bits)
    genesisblock.nonce            = struct.pack("<I", nonce)
    return block_header.build(genesisblock)

# https://en.bitcoin.it/wiki/Block_hashing_algorithm
def generate_hash(data_block, algorithm, start_nonce, bits):
    print("Searching for genesis hash..")
    nonce        = start_nonce
    last_updated = time.time()
    # https://en.bitcoin.it/wiki/Difficulty
    target = (bits & 0xffffff) * 2 ** (8 * ((bits >> 24) - 3))
    
    while True:
        sha256_hash, header_hash = generate_hashes_from_block(data_block, algorithm)
        last_updated = calculate_hashrate(nonce, last_updated)
        if is_genesis_hash(header_hash, target):
            if algorithm in ["X11", "X13", "X15"]:
                return (header_hash, nonce)
            return (sha256_hash, nonce)
        else:
            nonce += 1
            # Replace the last 4 bytes (the nonce) with the new nonce
            data_block = data_block[:-4] + struct.pack("<I", nonce)

def generate_hashes_from_block(data_block, algorithm):
    sha256_hash = hashlib.sha256(hashlib.sha256(data_block).digest()).digest()[::-1]
    header_hash = b""
    if algorithm == "scrypt":
        header_hash = scrypt.hash(data_block, data_block, 1024, 1, 1, 32)[::-1]
    elif algorithm == "SHA256":
        header_hash = sha256_hash
    elif algorithm == "X11":
        try:
            import xcoin_hash
        except ImportError:
            sys.exit("Cannot run X11 algorithm: module xcoin_hash not found")
        header_hash = xcoin_hash.getPoWHash(data_block)[::-1]
    elif algorithm == "X13":
        try:
            import x13_hash
        except ImportError:
            sys.exit("Cannot run X13 algorithm: module x13_hash not found")
        header_hash = x13_hash.getPoWHash(data_block)[::-1]
    elif algorithm == "X15":
        try:
            import x15_hash
        except ImportError:
            sys.exit("Cannot run X15 algorithm: module x15_hash not found")
        header_hash = x15_hash.getPoWHash(data_block)[::-1]
    return sha256_hash, header_hash

def is_genesis_hash(header_hash, target):
    # In Python 3, use the .hex() method
    return int(header_hash.hex(), 16) < target

def calculate_hashrate(nonce, last_updated):
    if nonce % 1000000 == 999999:
        now = time.time()
        hashrate = round(1000000 / (now - last_updated))
        generation_time = round((2 ** 32) / hashrate / 3600, 1)
        sys.stdout.write("\r{} hash/s, estimate: {} h".format(hashrate, generation_time))
        sys.stdout.flush()
        return now
    else:
        return last_updated

def print_block_info(options, hash_merkle_root):
    print("algorithm: "    + options.algorithm)
    print("merkle hash: "  + hash_merkle_root[::-1].hex())
    print("pszTimestamp: " + options.timestamp)
    print("pubkey: "       + options.pubkey)
    print("time: "         + str(options.time))
    print("bits: "         + str(hex(options.bits)))

def announce_found_genesis(genesis_hash, nonce):
    print("genesis hash found!")
    print("nonce: "        + str(nonce))
    print("genesis hash: " + genesis_hash.hex())

# GOGOGO!
if __name__ == "__main__":
    main()
