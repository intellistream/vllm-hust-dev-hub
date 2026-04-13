#ifndef HCCL_COMPAT_H_
#define HCCL_COMPAT_H_

#include <acl/acl.h>
#include <hccl/hccl_types.h>

#ifdef __cplusplus
extern "C" {
#endif

extern HcclResult HcclGetRootInfoV2(HcclRootInfo *rootInfo);
extern HcclResult HcclCommInitRootInfoV2(uint32_t nRanks, const HcclRootInfo *rootInfo, uint32_t rank, HcclComm *comm);
extern HcclResult HcclCommInitAllV2(uint32_t ndev, int32_t *devices, HcclComm *comms);
extern HcclResult HcclCommDestroyV2(HcclComm comm);
extern HcclResult HcclGetRankSizeV2(HcclComm comm, uint32_t *rankSize);
extern HcclResult HcclGetRankIdV2(HcclComm comm, uint32_t *rank);

extern HcclResult HcclAllReduceV2(const void *sendBuf, void *recvBuf, uint64_t count, HcclDataType dataType,
                                  HcclReduceOp op, HcclComm comm, aclrtStream stream);
extern HcclResult HcclAllGatherV2(const void *sendBuf, void *recvBuf, uint64_t count, HcclDataType dataType,
                                  HcclComm comm, aclrtStream stream);
extern HcclResult HcclBroadcastV2(void *buf, uint64_t count, HcclDataType dataType, uint32_t root, HcclComm comm,
                                  aclrtStream stream);
extern HcclResult HcclReduceV2(const void *sendBuf, void *recvBuf, uint64_t count, HcclDataType dataType,
                               HcclReduceOp op, uint32_t root, HcclComm comm, aclrtStream stream);
extern HcclResult HcclScatterV2(const void *sendBuf, void *recvBuf, uint64_t count, HcclDataType dataType,
                                uint32_t root, HcclComm comm, aclrtStream stream);
extern HcclResult HcclReduceScatterV2(const void *sendBuf, void *recvBuf, uint64_t count, HcclDataType dataType,
                                      HcclReduceOp op, HcclComm comm, aclrtStream stream);
extern HcclResult HcclAlltoAllV2(const void *sendBuf, uint64_t sendCount, HcclDataType sendType, void *recvBuf,
                                 uint64_t recvCount, HcclDataType recvType, HcclComm comm, aclrtStream stream);

#ifdef __cplusplus
}

static inline HcclResult HcclGetRootInfo(HcclRootInfo *rootInfo)
{
    return HcclGetRootInfoV2(rootInfo);
}

static inline HcclResult HcclCommInitRootInfo(uint32_t nRanks, const HcclRootInfo *rootInfo, uint32_t rank,
                                              HcclComm *comm)
{
    return HcclCommInitRootInfoV2(nRanks, rootInfo, rank, comm);
}

static inline HcclResult HcclCommInitAll(uint32_t ndev, int32_t *devices, HcclComm *comms)
{
    return HcclCommInitAllV2(ndev, devices, comms);
}

static inline HcclResult HcclCommDestroy(HcclComm comm)
{
    return HcclCommDestroyV2(comm);
}

static inline HcclResult HcclGetRankSize(HcclComm comm, uint32_t *rankSize)
{
    return HcclGetRankSizeV2(comm, rankSize);
}

static inline HcclResult HcclGetRankId(HcclComm comm, uint32_t *rank)
{
    return HcclGetRankIdV2(comm, rank);
}

static inline HcclResult HcclAllReduce(const void *sendBuf, void *recvBuf, uint64_t count, HcclDataType dataType,
                                       HcclReduceOp op, HcclComm comm, aclrtStream stream)
{
    return HcclAllReduceV2(sendBuf, recvBuf, count, dataType, op, comm, stream);
}

static inline HcclResult HcclAllGather(const void *sendBuf, void *recvBuf, uint64_t count, HcclDataType dataType,
                                       HcclComm comm, aclrtStream stream)
{
    return HcclAllGatherV2(sendBuf, recvBuf, count, dataType, comm, stream);
}

static inline HcclResult HcclBroadcast(void *buf, uint64_t count, HcclDataType dataType, uint32_t root,
                                       HcclComm comm, aclrtStream stream)
{
    return HcclBroadcastV2(buf, count, dataType, root, comm, stream);
}

static inline HcclResult HcclReduce(const void *sendBuf, void *recvBuf, uint64_t count, HcclDataType dataType,
                                    HcclReduceOp op, uint32_t root, HcclComm comm, aclrtStream stream)
{
    return HcclReduceV2(sendBuf, recvBuf, count, dataType, op, root, comm, stream);
}

static inline HcclResult HcclScatter(const void *sendBuf, void *recvBuf, uint64_t count, HcclDataType dataType,
                                     uint32_t root, HcclComm comm, aclrtStream stream)
{
    return HcclScatterV2(sendBuf, recvBuf, count, dataType, root, comm, stream);
}

static inline HcclResult HcclReduceScatter(const void *sendBuf, void *recvBuf, uint64_t count,
                                           HcclDataType dataType, HcclReduceOp op, HcclComm comm,
                                           aclrtStream stream)
{
    return HcclReduceScatterV2(sendBuf, recvBuf, count, dataType, op, comm, stream);
}

static inline HcclResult HcclAlltoAll(const void *sendBuf, uint64_t sendCount, HcclDataType sendType, void *recvBuf,
                                      uint64_t recvCount, HcclDataType recvType, HcclComm comm,
                                      aclrtStream stream)
{
    return HcclAlltoAllV2(sendBuf, sendCount, sendType, recvBuf, recvCount, recvType, comm, stream);
}
#endif

#endif