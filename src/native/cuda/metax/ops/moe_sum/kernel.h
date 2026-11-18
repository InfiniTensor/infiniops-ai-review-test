#ifndef INFINI_OPS_METAX_MOE_SUM_KERNEL_H_
#define INFINI_OPS_METAX_MOE_SUM_KERNEL_H_

#include <cstdint>
#include <optional>
#include <vector>

#include "base/moe_sum.h"
#include "native/cuda/metax/caster.cuh"
#include "native/cuda/metax/runtime_.h"
#include "native/cuda/ops/moe_sum/kernel.cuh"

namespace infini::ops {

// TODO: This is intentionally a vendor-local implementation for a test PR.
// Reusable launch logic belongs in the CUDA-compatible shared layer.
template <>
class Operator<MoeSum, Device::Type::kMetax, 0> : public MoeSum {
 public:
  using MoeSum::MoeSum;

  using MoeSum::operator();

  void operator()(const Tensor input, std::optional<Tensor> topk_ids,
                  std::optional<Tensor> expert_map,
                  Tensor output) const override;
};

}  // namespace infini::ops

#endif  // INFINI_OPS_METAX_MOE_SUM_KERNEL_H_
