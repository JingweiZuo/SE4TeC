import sys,os
import numpy as np
import similarity_measures as sm

from pyspark import SparkContext, SparkConf
from pyspark.sql.types import ArrayType, FloatType, IntegerType, StringType, StructField, StructType, MapType
from pyspark.sql import SparkSession
from pyspark.sql.functions import udf, split, hash, col, collect_list, collect_set, _collect_list_doc, _collect_set_doc

master_id = "local"
#master_id = "spark://spark-master:7077"
appname = "distributed_use"
#spark = SparkSession.builder.master(master_id).appName(appname).getOrCreate()
sc = SparkContext(appName=appname)
sc.setLogLevel("INFO")# or "WARN"

#sc.addPyFile("similarity_measures.py")
spark = SparkSession(sc)
m = 10
step = 4

def input_data(path, filename, schemaString):
    fields = [StructField(field_name, StringType(), True) for field_name in schemaString.split()]
    schema = StructType(fields)
    #df = spark.read.csv(path + filename, schema=schema)
    df = spark.read.csv(path + filename, sep=";", schema=schema)
    dataType = StructType([StructField("Class", IntegerType(), True), StructField("Timeseries", ArrayType(FloatType()), True)])
    def split_cols(array):
        #Class  = int(float(array[1]))
        #timeseries = array[2:len(array)]
        Class = int(float(array[0]))
        timeseries = array[1:len(array)]
        timeseries = [float(value) for value in timeseries]
        return (Class, timeseries)
    split_cols = udf(split_cols, dataType)
    #df = df.withColumn('text', split_cols(split('class_timeseries', '\\s+'))).select(hash(col('text.Timeseries')).alias('id'), col('text.*'))
    df = df.withColumn('text', split_cols(split('class_timeseries', ','))).select(
        hash(col('text.Timeseries')).alias('id'), col('text.*'))
    df_csv = df.select(col('Timeseries'))
    return df

def computeMP(T_source, T_target, m, step):
    n = len(T_source)
    indexes = n - m + 1
    MP12 = []  # Matrix Profile
    DP_all = {}  # Distance Profiles for All Index in the timeseries
    for index in range(0, indexes, step):
        index_m = index + m
        query = T_source[index:index_m]
        # compute Distance Profile(DP)
        #DP = mass_v2(data, query)
        # if std(query)==0, then 'mass_v2' will return a NAN, ignore this Distance profile
        #Numpy will generate the result with datatype 'float64', where std(query) maybe equals to 'x*e-17', but not 0
        if round(np.std(query),4) == 0:
            continue
        else:
            # conversion between numpy array and list
            DP_all[index] = sm.mass_v2(T_target, query).tolist()
            MP12.append(min(DP_all[index]))
            index += 1
    return DP_all, MP12

def computeDD(c, T):
    #input,
        # c: class of T
        # T: Array[float]
        # D: List[Row]
        # m, step
    D = df_bc.value
    distSameClass = []
    distDiffClass = []
    mp_map = {}
    dp_map = {}
    source = T
    for row in D:
        target = np.array(row.Timeseries)
        dp, mp = computeMP(source, target, m, step)
        mp_map.update({row.id : mp})
        #dp_map.update({row.id : dp})
        if row.Class == c:
            distSameClass.append(mp)
        else:
            distDiffClass.append(mp)
    avgdistSameC = np.mean(distSameClass, axis = 0 )
    avgdistDiffC = np.mean(distDiffClass, axis = 0 )
    DD = np.subtract(avgdistDiffC, avgdistSameC)
    distThresh = avgdistSameC
    return (DD.tolist(), distThresh.tolist(), mp_map)

def findTopK(id_list, DD_list, th_list):
    #id_list: List[Int]
    #DD_list: List[List[Float]]
    #th_list: List[List[Float]]

    # take the k first values as the initial values, then update them
    keys = [(init_id, init_id) for init_id in range(0, k)]
    #keys = range(0, k)
    # take top k shapelets for each class
    topk_dict = dict.fromkeys(keys, float('-inf'))
    topk_dict2 = dict.fromkeys(keys, (float('-inf'),float('-inf')))
    for idxDD, DD in enumerate(DD_list):
        for indice, dd in enumerate(DD):
            minVal = min(topk_dict.values())
            for id_indice, dd_topk in topk_dict.items():
                if dd_topk == minVal and dd_topk < dd:
                    topk_dict.pop(id_indice)
                    topk_dict2.pop(id_indice)
                    composeKey = (id_list[idxDD],indice)
                    composeVal = (dd, th_list[idxDD][indice])
                    topk_dict.update({composeKey: dd})
                    topk_dict2.update({composeKey: composeVal})
                    break
    return topk_dict2

def computeDD_all_length(c, id, T):
    # input,
    # c: class of T
    # T: Array[float]
    # D: List[Row]
    # m, step
    D = df_bc.value
    mp_map = {}
    dp_map = {}
    lenT = len(T)
    All_data = np.zeros(shape=[(int(lenT / 2) - 2) * k, 5])
    All_data = All_data.astype(str)

    kk = k
    for l in range(2, int(lenT / 2)):
        distSameClass = []
        distDiffClass = []
        for row in D:
            target = np.array(row.Timeseries)
            dp, mp = computeMP(T, target, l, step)
            # mp_map.update({row.id : mp})
            # dp_map.update({row.id : dp})
            if row.Class == c:
                distSameClass.append(mp)
            else:
                distDiffClass.append(mp)
        avgdistSameC = np.mean(distSameClass, axis=0)
        avgdistDiffC = np.mean(distDiffClass, axis=0)
        DD = np.subtract(avgdistDiffC, avgdistSameC)
        DD = np.divide(DD, l ** 0.5)    #normalization of DD
        distThresh = avgdistSameC

        #topK value selection for each length of target TS
        # len(DD): (L_max-2)/step
        if k >= len(DD):
            kk = len(DD)
        kIndice = np.argpartition(DD, -kk, axis=0)[-kk:]
        kDD = DD[kIndice][:, np.newaxis]
        kThresh = distThresh[kIndice][:, np.newaxis]
        kIndice = kIndice[:, np.newaxis]
        L = np.full((kk,1), l, dtype=int)
        ID = np.full((kk,1), id, dtype=int)
        DD_Thresh_Indice = np.concatenate((kDD, kThresh, kIndice, ID, L), axis=1)
        All_data[(l-2)*kk : (l-2+1)*kk] = DD_Thresh_Indice
    # topK value selection for target TS
    # remove the repetitive

    B = All_data[:,0].astype(float)
    idxB = np.argpartition(B, -kk, axis=0)[-kk:]
    def toTuple(data):
        return (float(data[0]), float(data[1]), int(float(data[2])), int(float(data[3])), int(float(data[4])))
    return list(map(toTuple, All_data[idxB]))

def findTopK2(LL):
    flat_list = [item for sublist in LL for item in sublist]
    flat_list = sorted(flat_list, key=lambda tuple: tuple[0], reverse=True)
    return flat_list[0:k]

def extractRawData(text):
    #input text: (DD, Thresh, indice, T_id, length)
    #output: (DD, Thresh, RawData)
    output = []
    bc = df_bc.value
    for shapelet_idx in text:
        s_DD = shapelet_idx.DD
        s_Thresh = shapelet_idx.Thresh
        s_indice = shapelet_idx.indice
        s_id = shapelet_idx.T_id
        s_length = shapelet_idx.length
        #BC[LIST]: LIST, take the unique element in the list
        rawTS = [element.Timeseries for element in bc if element.id == s_id ][0]
        rawShapelet = rawTS[s_indice:s_indice + s_length]
        output.append((s_DD, s_Thresh, rawShapelet))
    return output

if __name__ == '__main__':
    path = "/Users/Jingwei/PycharmProjects/distributed_use/venv/TestDataset/"
    #path = "/TestDataset/"
    filename = "UCR_TS_Archive_2015/SonyAIBORobotSurface/SonyAIBORobotSurface_TRAIN"
    schemaString = "class_timeseries"
    k = 20

    df= input_data(path, filename, schemaString)
    df.repartition(4, "class")
    # broadcast variable: a list of Row, df_bc: List[Row(id: int, Class: string, Timeseries: string)]
    df_bc = sc.broadcast(df.collect())
    #TEST POINT 1: print(df.groupBy('Class').count().collect())
    '''
    dataTypeDD = StructType([StructField("DD", ArrayType(FloatType()), True),
                             StructField("distThresh", ArrayType(FloatType()), True),
                             StructField("mp_map", MapType(IntegerType(), ArrayType(FloatType())))
                             #StructField("dp_map", MapType(IntegerType(), MapType(IntegerType(), ArrayType(FloatType()))))
                             ])
    
    computeDD = udf(computeDD, dataTypeDD)
    #dfDD: id, Class, DD, distThresh, mp_map, dp_map
    dfDD = df.withColumn('text', col=computeDD('Class', 'Timeseries')).select(col('id'), col('Class'), col('text.*'))
    #TEST POINT 2: print(dfDD.first())
    NewdfDD = dfDD.select("Class", "id", "DD", "distThresh")
    NewdfDD = NewdfDD.groupBy("Class").agg(collect_list("id").alias("id_list"),
                                collect_list("DD").alias("DD_list"),
                                collect_list("distThresh").alias("th_list"))

    dataType_NewdfDD = MapType(StructType([StructField('id', IntegerType(), True), StructField('indice', IntegerType(), True)]),
                               StructType([StructField('DD', FloatType(), True), StructField('Thresh', FloatType(), True)]))
    findTopK = udf(findTopK, dataType_NewdfDD)
    NewdfDD = NewdfDD.select(col('Class'), findTopK('id_list', 'DD_list', 'th_list').alias("text")) #!!!
    #NewdfDD = NewdfDD.withColumn('text', col = findTopK('id_list', 'DD_list', 'th_list')).select(col('Class'), col('text'))  # !!!
    print(NewdfDD.first())'''

    dataTypeAllLength = ArrayType(StructType([StructField("DD", FloatType(),True),
                                     StructField("Thresh", FloatType(),True),
                                     StructField("indice", IntegerType(),True),
                                     StructField("T_id", IntegerType(), True),
                                     StructField("length", IntegerType(),True)]))
    computeDD_all_length = udf(computeDD_all_length, dataTypeAllLength)
    dfDD = df.select(col('id'), col('Class'), computeDD_all_length('Class', 'id', 'Timeseries').alias("text"))
    #print(dfDD.first())
    NewdfDD = dfDD.groupBy("Class").agg(collect_list("text").alias("text_list"))
    #print(NewdfDD.first())

    findTopK2 = udf(findTopK2, dataTypeAllLength)
    NewdfDD = NewdfDD.select(col('Class'), findTopK2('text_list').alias("text")).cache()

    '''shapelet_index = NewdfDD.toPandas()
    df = df.toPandas()
    shapelet_index[['text']]'''

    dataTypeResult = ArrayType(StructType([StructField("DD", FloatType(), True),
                                           StructField("Thresh", FloatType(), True),
                                           StructField("RawData", ArrayType(FloatType(), True))
                                           ]))
    extractRawData = udf(extractRawData, dataTypeResult)
    ShapeletDF = NewdfDD.select(col('Class'), extractRawData('text').alias('Shapelets'))
    print(ShapeletDF.first())