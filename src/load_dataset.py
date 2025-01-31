import glob
import numpy as np
import os
import tensorflow as tf
import tqdm
import sys
import magic


def load_dataset(enc, path, combine):
    paths = []
    if os.path.isfile(path):
        # Simple file
        paths.append(path)
    elif os.path.isdir(path):
        # Directory
        for (dirpath, _, fnames) in os.walk(path):
            for fname in fnames:
                paths.append(os.path.join(dirpath, fname))
    else:
        # Assume glob
        paths = glob.glob(path)

    token_chunks = []
    raw_text = ''
    files = tqdm.tqdm(paths)
    failed_files = []
    print("start preprocessing")
    for i, path in enumerate(files):
        if path.endswith('.npz'):
            # Pre-encoded
            with np.load(path) as npz:
                for item in npz.files:
                    token_chunks.append(npz[item])
        else:
            if path.endswith(".java"):
                # Plain text
                try:
                    encoding = get_encoding(path)
                    with open(path, 'r', encoding=encoding) as fp:
                        try:
                            raw_text += fp.read()
                        except Exception:
                            print(str(path) + " has wrong encoding")
                            sys.exit(0)
                    if len(raw_text) >= combine:
                        tokens = np.stack(enc.encode(raw_text))
                        token_chunks.append(tokens)
                        raw_text = ''
                    else:
                        raw_text += '<|endoftext|>'
                except UnicodeDecodeError:
                    failed_files.append([path, "UnicodeDecodeError"])
                except LookupError:
                    failed_files.append([path, "LookupError"])
                except FileNotFoundError:
                    failed_files.append([path, "FileNotFoundError"])
            else:
                #print("this is not a java file: " + path)
                failed_files.append([path, "NotAJavaFile"])
    print("failed files: " + str(len(failed_files)))
    with open("failed_files.txt", "a") as f:
        for file, reason in failed_files:
            try:
                f.write("[" + reason + "] " + file + "\n")
            except Exception:
                print("a file is so completely out of format, that even it could not be displayed here - skipping")

    if raw_text:
        tokens = np.stack(enc.encode(raw_text))
        token_chunks.append(tokens)
    return token_chunks


def get_encoding(path):
    m = magic.Magic(mime_encoding=True)
    input_file = open(path)
    blob = input_file.read()
    encoding = m.from_buffer(blob)
    input_file.close()
    return encoding


def binary_search(f, lo, hi):
    if f(lo) or not f(hi):
        return None
    while hi > lo + 1:
        mid = (lo + hi) // 2
        if f(mid):
            hi = mid
        else:
            lo = mid
    return hi


class Sampler(object):
    """Fairly samples a slice from a set of variable sized chunks.

    'Fairly' means that the distribution is the same as sampling from one concatenated chunk,
    but without crossing chunk boundaries."""

    def __init__(self, chunks, seed=None):
        self.chunks = chunks
        self.total_size = sum(chunk.shape[0] for chunk in chunks)
        self.boundaries = [0]
        for i in range(len(chunks)):
            self.boundaries.append(self.boundaries[-1] + chunks[i].shape[0])
        self.rs = np.random.RandomState(seed=seed)

    def sample(self, length):
        assert length < self.total_size // len(
            self.chunks
        ), "Dataset files are too small to sample {} tokens at a time".format(
            length)
        while True:
            index = self.rs.randint(0, self.total_size - length - 1)
            i = binary_search(lambda j: self.boundaries[j] > index, 0,
                              len(self.boundaries) - 1) - 1
            if self.boundaries[i + 1] > index + length:
                within_chunk = index - self.boundaries[i]
                return self.chunks[i][within_chunk:within_chunk + length]
