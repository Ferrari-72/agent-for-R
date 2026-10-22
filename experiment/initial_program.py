"""Find a pairwise contraction path for one tensor network.

The path uses positions in the current tensor list. After each contraction,
remove both tensors and append the resulting tensor to the end.
"""

# EVOLVE-BLOCK-START
def find_path(inputs, output, sizes, seed=0):
    """Return exactly len(inputs) - 1 pairs of current tensor positions."""
    import opt_einsum as oe

    return [tuple(pair) for pair in oe.paths.greedy(
        [set(tensor) for tensor in inputs], set(output), sizes
    )]
# EVOLVE-BLOCK-END
