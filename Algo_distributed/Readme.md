## The file shows the instructions for executing the distributed SMAP 

### - Shapelet extraction with MAtrix Profile



### Requirements:

- Pyspark & Spark 2.3.0
- numpy 



### Running command:

```python
PYSPARK_PYTHON=python3 spark-submit distributed_smap.py ./Dataset/ECG200/ ECG200_TRAIN
```



### Results:

- The generated Shapelets will be saved in several ".csv" files, each file matches to one class. The file format is shown as following:

  | Class | (Discriminative Power, Threshold Distance, [Shapelet data]) |
  | :---: | :---------------------------------------------------------: |

