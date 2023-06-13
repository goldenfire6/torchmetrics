# Copyright The Lightning team.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import json
from collections import namedtuple
from copy import deepcopy
from functools import partial

import numpy as np
import pytest
import torch
from pycocotools import mask
from pycocotools.coco import COCO
from pycocotools.cocoeval import COCOeval
from torch import IntTensor, Tensor
from torchmetrics.detection.mean_ap import MeanAveragePrecision, _HidePrints
from torchmetrics.utilities.imports import _PYCOCOTOOLS_AVAILABLE, _TORCHVISION_GREATER_EQUAL_0_8

from unittests.detection import _DETECTION_BBOX, _DETECTION_SEGM, _DETECTION_VAL, _SAMPLE_DETECTION_SEGMENTATION
from unittests.helpers.testers import MetricTester

_pytest_condition = not (_PYCOCOTOOLS_AVAILABLE and _TORCHVISION_GREATER_EQUAL_0_8)


def _generate_coco_inputs(iou_type):
    """Generates inputs for the MAP metric.

    The inputs are generated from the official COCO results json files:
    https://github.com/cocodataset/cocoapi/tree/master/results
    and should therefore correspond directly to the result on the webpage
    """
    batched_preds, batched_target = MeanAveragePrecision.coco_to_tm(
        _DETECTION_BBOX if iou_type == "bbox" else _DETECTION_SEGM, _DETECTION_VAL, iou_type
    )

    # create 10 batches of 10 preds/targets each
    batched_preds = [batched_preds[10 * i : 10 * (i + 1)] for i in range(10)]
    batched_target = [batched_target[10 * i : 10 * (i + 1)] for i in range(10)]
    return batched_preds, batched_target


_coco_bbox_input = _generate_coco_inputs("bbox")
_coco_segm_input = _generate_coco_inputs("segm")


def _compare_again_coco_fn(preds, target, iou_type, class_metrics=True):
    """Taken from https://github.com/cocodataset/cocoapi/blob/master/PythonAPI/pycocoEvalDemo.ipynb."""
    gt = COCO(_DETECTION_VAL)
    dt = gt.loadRes(_DETECTION_BBOX if iou_type == "bbox" else _DETECTION_SEGM)

    coco_eval = COCOeval(gt, dt, iou_type)
    with _HidePrints():
        coco_eval.evaluate()
        coco_eval.accumulate()
        coco_eval.summarize()
    global_stats = deepcopy(coco_eval.stats)

    map_per_class_values = torch.Tensor([-1])
    mar_100_per_class_values = torch.Tensor([-1])
    classes = torch.tensor(
        list(set(torch.arange(91).tolist()) - {0, 12, 19, 26, 29, 30, 45, 66, 68, 69, 71, 76, 83, 87, 89})
    )

    if class_metrics:
        map_per_class_list = []
        mar_100_per_class_list = []
        for class_id in classes.tolist():
            coco_eval.params.catIds = [class_id]
            with _HidePrints():
                coco_eval.evaluate()
                coco_eval.accumulate()
                coco_eval.summarize()
            class_stats = coco_eval.stats
            map_per_class_list.append(torch.Tensor([class_stats[0]]))
            mar_100_per_class_list.append(torch.Tensor([class_stats[8]]))

        map_per_class_values = torch.Tensor(map_per_class_list)
        mar_100_per_class_values = torch.Tensor(mar_100_per_class_list)

    return {
        "map": Tensor([global_stats[0]]),
        "map_50": Tensor([global_stats[1]]),
        "map_75": Tensor([global_stats[2]]),
        "map_small": Tensor([global_stats[3]]),
        "map_medium": Tensor([global_stats[4]]),
        "map_large": Tensor([global_stats[5]]),
        "mar_1": Tensor([global_stats[6]]),
        "mar_10": Tensor([global_stats[7]]),
        "mar_100": Tensor([global_stats[8]]),
        "mar_small": Tensor([global_stats[9]]),
        "mar_medium": Tensor([global_stats[10]]),
        "mar_large": Tensor([global_stats[11]]),
        "map_per_class": map_per_class_values,
        "mar_100_per_class": mar_100_per_class_values,
        "classes": classes,
    }


@pytest.mark.skipif(_pytest_condition, reason="test requires that torchvision=>0.8.0 and pycocotools is installed")
@pytest.mark.parametrize("iou_type", ["bbox", "segm"])
@pytest.mark.parametrize("ddp", [False, True])
class TestMAPUsingCOCOReference(MetricTester):
    """Test map metric on the reference coco data."""

    atol = 1e-1

    def test_map(self, iou_type, ddp):
        """Test modular implementation for correctness."""
        preds, target = _coco_bbox_input if iou_type == "bbox" else _coco_segm_input
        self.run_class_metric_test(
            ddp=ddp,
            preds=preds,
            target=target,
            metric_class=MeanAveragePrecision,
            reference_metric=partial(_compare_again_coco_fn, iou_type=iou_type, class_metrics=True),
            metric_args={"iou_type": iou_type, "class_metrics": True},
            check_batch=False,
        )


Input = namedtuple("Input", ["preds", "target"])


_inputs = Input(
    preds=[
        [
            {
                "boxes": Tensor([[258.15, 41.29, 606.41, 285.07]]),
                "scores": Tensor([0.236]),
                "labels": IntTensor([4]),
            },  # coco image id 42
            {
                "boxes": Tensor([[61.00, 22.75, 565.00, 632.42], [12.66, 3.32, 281.26, 275.23]]),
                "scores": Tensor([0.318, 0.726]),
                "labels": IntTensor([3, 2]),
            },  # coco image id 73
        ],
        [
            {
                "boxes": Tensor(
                    [
                        [87.87, 276.25, 384.29, 379.43],
                        [0.00, 3.66, 142.15, 316.06],
                        [296.55, 93.96, 314.97, 152.79],
                        [328.94, 97.05, 342.49, 122.98],
                        [356.62, 95.47, 372.33, 147.55],
                        [464.08, 105.09, 495.74, 146.99],
                        [276.11, 103.84, 291.44, 150.72],
                    ]
                ),
                "scores": Tensor([0.546, 0.3, 0.407, 0.611, 0.335, 0.805, 0.953]),
                "labels": IntTensor([4, 1, 0, 0, 0, 0, 0]),
            },  # coco image id 74
            {
                "boxes": Tensor(
                    [
                        [72.92, 45.96, 91.23, 80.57],
                        [45.17, 45.34, 66.28, 79.83],
                        [82.28, 47.04, 99.66, 78.50],
                        [59.96, 46.17, 80.35, 80.48],
                        [75.29, 23.01, 91.85, 50.85],
                        [71.14, 1.10, 96.96, 28.33],
                        [61.34, 55.23, 77.14, 79.57],
                        [41.17, 45.78, 60.99, 78.48],
                        [56.18, 44.80, 64.42, 56.25],
                    ]
                ),
                "scores": Tensor([0.532, 0.204, 0.782, 0.202, 0.883, 0.271, 0.561, 0.204, 0.349]),
                "labels": IntTensor([49, 49, 49, 49, 49, 49, 49, 49, 49]),
            },  # coco image id 987 category_id 49
        ],
    ],
    target=[
        [
            {
                "boxes": Tensor([[214.1500, 41.2900, 562.4100, 285.0700]]),
                "labels": IntTensor([4]),
            },  # coco image id 42
            {
                "boxes": Tensor(
                    [
                        [13.00, 22.75, 548.98, 632.42],
                        [1.66, 3.32, 270.26, 275.23],
                    ]
                ),
                "labels": IntTensor([2, 2]),
            },  # coco image id 73
        ],
        [
            {
                "boxes": Tensor(
                    [
                        [61.87, 276.25, 358.29, 379.43],
                        [2.75, 3.66, 162.15, 316.06],
                        [295.55, 93.96, 313.97, 152.79],
                        [326.94, 97.05, 340.49, 122.98],
                        [356.62, 95.47, 372.33, 147.55],
                        [462.08, 105.09, 493.74, 146.99],
                        [277.11, 103.84, 292.44, 150.72],
                    ]
                ),
                "labels": IntTensor([4, 1, 0, 0, 0, 0, 0]),
            },  # coco image id 74
            {
                "boxes": Tensor(
                    [
                        [72.92, 45.96, 91.23, 80.57],
                        [50.17, 45.34, 71.28, 79.83],
                        [81.28, 47.04, 98.66, 78.50],
                        [63.96, 46.17, 84.35, 80.48],
                        [75.29, 23.01, 91.85, 50.85],
                        [56.39, 21.65, 75.66, 45.54],
                        [73.14, 1.10, 98.96, 28.33],
                        [62.34, 55.23, 78.14, 79.57],
                        [44.17, 45.78, 63.99, 78.48],
                        [58.18, 44.80, 66.42, 56.25],
                    ]
                ),
                "labels": IntTensor([49, 49, 49, 49, 49, 49, 49, 49, 49, 49]),
            },  # coco image id 987 category_id 49
        ],
    ],
)

# example from this issue https://github.com/Lightning-AI/torchmetrics/issues/943
_inputs2 = Input(
    preds=[
        [
            {
                "boxes": Tensor([[258.0, 41.0, 606.0, 285.0]]),
                "scores": Tensor([0.536]),
                "labels": IntTensor([0]),
            },
        ],
        [
            {
                "boxes": Tensor([[258.0, 41.0, 606.0, 285.0]]),
                "scores": Tensor([0.536]),
                "labels": IntTensor([0]),
            }
        ],
    ],
    target=[
        [
            {
                "boxes": Tensor([[214.0, 41.0, 562.0, 285.0]]),
                "labels": IntTensor([0]),
            }
        ],
        [
            {
                "boxes": Tensor([]),
                "labels": IntTensor([]),
            }
        ],
    ],
)

# Test empty preds case, to ensure bool inputs are properly casted to uint8
# From https://github.com/Lightning-AI/torchmetrics/issues/981
# and https://github.com/Lightning-AI/torchmetrics/issues/1147
_inputs3 = Input(
    preds=[
        [
            {
                "boxes": Tensor([[258.0, 41.0, 606.0, 285.0]]),
                "scores": Tensor([0.536]),
                "labels": IntTensor([0]),
            },
        ],
        [
            {"boxes": Tensor([]), "scores": Tensor([]), "labels": Tensor([])},
        ],
    ],
    target=[
        [
            {
                "boxes": Tensor([[214.0, 41.0, 562.0, 285.0]]),
                "labels": IntTensor([0]),
            }
        ],
        [
            {
                "boxes": Tensor([[1.0, 2.0, 3.0, 4.0]]),
                "scores": Tensor([0.8]),  # target does not have scores
                "labels": IntTensor([1]),
            },
        ],
    ],
)


@pytest.mark.skipif(_pytest_condition, reason="test requires that torchvision=>0.8.0 is installed")
def test_error_on_wrong_init():
    """Test class raises the expected errors."""
    MeanAveragePrecision()  # no error

    with pytest.raises(ValueError, match="Expected argument `class_metrics` to be a boolean"):
        MeanAveragePrecision(class_metrics=0)


@pytest.mark.skipif(_pytest_condition, reason="test requires that torchvision=>0.8.0 is installed")
def test_empty_preds():
    """Test empty predictions."""
    metric = MeanAveragePrecision()

    metric.update(
        [{"boxes": Tensor([]), "scores": Tensor([]), "labels": IntTensor([])}],
        [{"boxes": Tensor([[214.1500, 41.2900, 562.4100, 285.0700]]), "labels": IntTensor([4])}],
    )
    metric.compute()


@pytest.mark.skipif(_pytest_condition, reason="test requires that torchvision=>0.8.0 is installed")
def test_empty_ground_truths():
    """Test empty ground truths."""
    metric = MeanAveragePrecision()

    metric.update(
        [
            {
                "boxes": Tensor([[214.1500, 41.2900, 562.4100, 285.0700]]),
                "scores": Tensor([0.5]),
                "labels": IntTensor([4]),
            }
        ],
        [{"boxes": Tensor([]), "labels": IntTensor([])}],
    )
    metric.compute()


@pytest.mark.skipif(_pytest_condition, reason="test requires that torchvision=>0.8.0 is installed")
def test_empty_ground_truths_xywh():
    """Test empty ground truths in xywh format."""
    metric = MeanAveragePrecision(box_format="xywh")

    metric.update(
        [
            {
                "boxes": Tensor([[214.1500, 41.2900, 348.2600, 243.7800]]),
                "scores": Tensor([0.5]),
                "labels": IntTensor([4]),
            }
        ],
        [{"boxes": Tensor([]), "labels": IntTensor([])}],
    )
    metric.compute()


@pytest.mark.skipif(_pytest_condition, reason="test requires that torchvision=>0.8.0 is installed")
def test_empty_preds_xywh():
    """Test empty predictions in xywh format."""
    metric = MeanAveragePrecision(box_format="xywh")

    metric.update(
        [{"boxes": Tensor([]), "scores": Tensor([]), "labels": IntTensor([])}],
        [{"boxes": Tensor([[214.1500, 41.2900, 348.2600, 243.7800]]), "labels": IntTensor([4])}],
    )
    metric.compute()


@pytest.mark.skipif(_pytest_condition, reason="test requires that torchvision=>0.8.0 is installed")
def test_empty_ground_truths_cxcywh():
    """Test empty ground truths in cxcywh format."""
    metric = MeanAveragePrecision(box_format="cxcywh")

    metric.update(
        [
            {
                "boxes": Tensor([[388.2800, 163.1800, 348.2600, 243.7800]]),
                "scores": Tensor([0.5]),
                "labels": IntTensor([4]),
            }
        ],
        [{"boxes": Tensor([]), "labels": IntTensor([])}],
    )
    metric.compute()


@pytest.mark.skipif(_pytest_condition, reason="test requires that torchvision=>0.8.0 is installed")
def test_empty_preds_cxcywh():
    """Test empty predictions in cxcywh format."""
    metric = MeanAveragePrecision(box_format="cxcywh")

    metric.update(
        [{"boxes": Tensor([]), "scores": Tensor([]), "labels": IntTensor([])}],
        [{"boxes": Tensor([[388.2800, 163.1800, 348.2600, 243.7800]]), "labels": IntTensor([4])}],
    )
    metric.compute()


_gpu_test_condition = not torch.cuda.is_available()


def _move_to_gpu(inputs):
    for x in inputs:
        for key in x:
            if torch.is_tensor(x[key]):
                x[key] = x[key].to("cuda")
    return inputs


@pytest.mark.skipif(_pytest_condition, reason="test requires that torchvision=>0.8.0 is installed")
@pytest.mark.skipif(_gpu_test_condition, reason="test requires CUDA availability")
@pytest.mark.parametrize("inputs", [_inputs, _inputs2, _inputs3])
def test_map_gpu(inputs):
    """Test predictions on single gpu."""
    metric = MeanAveragePrecision()
    metric = metric.to("cuda")
    for preds, targets in zip(inputs.preds, inputs.target):
        metric.update(_move_to_gpu(preds), _move_to_gpu(targets))
    metric.compute()


@pytest.mark.skipif(_pytest_condition, reason="test requires that torchvision=>0.8.0 is installed")
@pytest.mark.skipif(_gpu_test_condition, reason="test requires CUDA availability")
def test_map_with_custom_thresholds():
    """Test that map works with custom iou thresholds."""
    metric = MeanAveragePrecision(iou_thresholds=[0.1, 0.2])
    metric = metric.to("cuda")
    for preds, targets in zip(_inputs.preds, _inputs.target):
        metric.update(_move_to_gpu(preds), _move_to_gpu(targets))
    res = metric.compute()
    assert res["map_50"].item() == -1
    assert res["map_75"].item() == -1


@pytest.mark.skipif(_pytest_condition, reason="test requires that pycocotools and torchvision=>0.8.0 is installed")
def test_empty_metric():
    """Test empty metric."""
    metric = MeanAveragePrecision()
    metric.compute()


@pytest.mark.skipif(_pytest_condition, reason="test requires that pycocotools and torchvision=>0.8.0 is installed")
def test_missing_pred():
    """One good detection, one false negative.

    Map should be lower than 1. Actually it is 0.5, but the exact value depends on where we are sampling (i.e. recall's
    values)
    """
    gts = [
        {"boxes": Tensor([[10, 20, 15, 25]]), "labels": IntTensor([0])},
        {"boxes": Tensor([[10, 20, 15, 25]]), "labels": IntTensor([0])},
    ]
    preds = [
        {"boxes": Tensor([[10, 20, 15, 25]]), "scores": Tensor([0.9]), "labels": IntTensor([0])},
        # Empty prediction
        {"boxes": Tensor([]), "scores": Tensor([]), "labels": IntTensor([])},
    ]
    metric = MeanAveragePrecision()
    metric.update(preds, gts)
    result = metric.compute()
    assert result["map"] < 1, "MAP cannot be 1, as there is a missing prediction."


@pytest.mark.skipif(_pytest_condition, reason="test requires that pycocotools and torchvision=>0.8.0 is installed")
def test_missing_gt():
    """The symmetric case of test_missing_pred.

    One good detection, one false positive. Map should be lower than 1. Actually it is 0.5, but the exact value depends
    on where we are sampling (i.e. recall's values)
    """
    gts = [
        {"boxes": Tensor([[10, 20, 15, 25]]), "labels": IntTensor([0])},
        {"boxes": Tensor([]), "labels": IntTensor([])},
    ]
    preds = [
        {"boxes": Tensor([[10, 20, 15, 25]]), "scores": Tensor([0.9]), "labels": IntTensor([0])},
        {"boxes": Tensor([[10, 20, 15, 25]]), "scores": Tensor([0.95]), "labels": IntTensor([0])},
    ]

    metric = MeanAveragePrecision()
    metric.update(preds, gts)
    result = metric.compute()
    assert result["map"] < 1, "MAP cannot be 1, as there is an image with no ground truth, but some predictions."


@pytest.mark.skipif(_pytest_condition, reason="test requires that torchvision=>0.8.0 is installed")
def test_segm_iou_empty_gt_mask():
    """Test empty ground truths."""
    metric = MeanAveragePrecision(iou_type="segm")

    metric.update(
        [{"masks": torch.randint(0, 1, (1, 10, 10)).bool(), "scores": Tensor([0.5]), "labels": IntTensor([4])}],
        [{"masks": Tensor([]), "labels": IntTensor([])}],
    )

    metric.compute()


@pytest.mark.skipif(_pytest_condition, reason="test requires that torchvision=>0.8.0 is installed")
def test_segm_iou_empty_pred_mask():
    """Test empty predictions."""
    metric = MeanAveragePrecision(iou_type="segm")

    metric.update(
        [{"masks": torch.BoolTensor([]), "scores": Tensor([]), "labels": IntTensor([])}],
        [{"masks": torch.randint(0, 1, (1, 10, 10)).bool(), "labels": IntTensor([4])}],
    )

    metric.compute()


@pytest.mark.skipif(_pytest_condition, reason="test requires that torchvision=>0.8.0 is installed")
def test_error_on_wrong_input():
    """Test class input validation."""
    metric = MeanAveragePrecision()

    metric.update([], [])  # no error

    with pytest.raises(ValueError, match="Expected argument `preds` to be of type Sequence"):
        metric.update(Tensor(), [])  # type: ignore

    with pytest.raises(ValueError, match="Expected argument `target` to be of type Sequence"):
        metric.update([], Tensor())  # type: ignore

    with pytest.raises(ValueError, match="Expected argument `preds` and `target` to have the same length"):
        metric.update([{}], [{}, {}])

    with pytest.raises(ValueError, match="Expected all dicts in `preds` to contain the `boxes` key"):
        metric.update(
            [{"scores": Tensor(), "labels": IntTensor}],
            [{"boxes": Tensor(), "labels": IntTensor()}],
        )

    with pytest.raises(ValueError, match="Expected all dicts in `preds` to contain the `scores` key"):
        metric.update(
            [{"boxes": Tensor(), "labels": IntTensor}],
            [{"boxes": Tensor(), "labels": IntTensor()}],
        )

    with pytest.raises(ValueError, match="Expected all dicts in `preds` to contain the `labels` key"):
        metric.update(
            [{"boxes": Tensor(), "scores": IntTensor}],
            [{"boxes": Tensor(), "labels": IntTensor()}],
        )

    with pytest.raises(ValueError, match="Expected all dicts in `target` to contain the `boxes` key"):
        metric.update(
            [{"boxes": Tensor(), "scores": IntTensor, "labels": IntTensor}],
            [{"labels": IntTensor()}],
        )

    with pytest.raises(ValueError, match="Expected all dicts in `target` to contain the `labels` key"):
        metric.update(
            [{"boxes": Tensor(), "scores": IntTensor, "labels": IntTensor}],
            [{"boxes": IntTensor()}],
        )

    with pytest.raises(ValueError, match="Expected all boxes in `preds` to be of type Tensor"):
        metric.update(
            [{"boxes": [], "scores": Tensor(), "labels": IntTensor()}],
            [{"boxes": Tensor(), "labels": IntTensor()}],
        )

    with pytest.raises(ValueError, match="Expected all scores in `preds` to be of type Tensor"):
        metric.update(
            [{"boxes": Tensor(), "scores": [], "labels": IntTensor()}],
            [{"boxes": Tensor(), "labels": IntTensor()}],
        )

    with pytest.raises(ValueError, match="Expected all labels in `preds` to be of type Tensor"):
        metric.update(
            [{"boxes": Tensor(), "scores": Tensor(), "labels": []}],
            [{"boxes": Tensor(), "labels": IntTensor()}],
        )

    with pytest.raises(ValueError, match="Expected all boxes in `target` to be of type Tensor"):
        metric.update(
            [{"boxes": Tensor(), "scores": Tensor(), "labels": IntTensor()}],
            [{"boxes": [], "labels": IntTensor()}],
        )

    with pytest.raises(ValueError, match="Expected all labels in `target` to be of type Tensor"):
        metric.update(
            [{"boxes": Tensor(), "scores": Tensor(), "labels": IntTensor()}],
            [{"boxes": Tensor(), "labels": []}],
        )


def _generate_random_segm_input(device):
    """Generate random inputs for mAP when iou_type=segm."""
    preds = []
    targets = []
    for _ in range(2):
        result = {}
        num_preds = torch.randint(0, 10, (1,)).item()
        result["scores"] = torch.rand((num_preds,), device=device)
        result["labels"] = torch.randint(0, 10, (num_preds,), device=device)
        result["masks"] = torch.randint(0, 2, (num_preds, 10, 10), device=device).bool()
        preds.append(result)
        gt = {}
        num_gt = torch.randint(0, 10, (1,)).item()
        gt["labels"] = torch.randint(0, 10, (num_gt,), device=device)
        gt["masks"] = torch.randint(0, 2, (num_gt, 10, 10), device=device).bool()
        targets.append(gt)
    return preds, targets


@pytest.mark.skipif(not torch.cuda.is_available(), reason="test requires cuda")
def test_device_changing():
    """See issue: https://github.com/Lightning-AI/torchmetrics/issues/1743.

    Checks that the custom apply function of the metric works as expected.
    """
    device = "cuda"
    metric = MeanAveragePrecision(iou_type="segm").to(device)

    for _ in range(2):
        preds, targets = _generate_random_segm_input(device)
        metric.update(preds, targets)

    metric = metric.cpu()
    val = metric.compute()
    assert isinstance(val, dict)
