# EDBS entries behind `storage-devices-and-io`

Pull any full entry with the `edbs-reference` skill:
`python3 <edbs-reference>/scripts/edbs.py show "<Entry>"`.
Entries are from the *Encyclopedia of Database Systems*, 2nd ed. (Liu and
Ozsu, Springer 2018). Many are short definitional entries from the storage
networking area; their value is vocabulary and the boundary of what the
layer below a DBMS does.

| Entry | Printed page | What it gives an engine builder |
|---|---|---|
| Active Storage | p.37 | Running filter/aggregate code on drive processors (Active Disks, IDISK); the origin of predicate pushdown into storage |
| Checksum and Cyclic Redundancy Check Mechanism | p.423 | Polynomial definition of CRC and its burst-detection guarantee; basis for page/log checksums |
| Data Center Energy Efficiency | p.735 | Energy proportionality, PUE, PCM wear and the semantic consequences of pervasive persistence |
| Direct Attached Storage | p.1119 | Definition of DAS and the server-centric architecture (stub entry) |
| Disk | p.1143 | HDD geometry, seek + rotational latency model, historical latency/bandwidth/capacity trends and why engines must favour sequential bulk I/O |
| Disk Power Saving | p.1144 | Drive power modes (standby, unloaded, low-RPM), spin-up penalties, multi-speed drives |
| Distributed File Systems | p.1186 | Client-server vs parallel DFS, naming, caching, replication; NFS, AFS, Lustre, GPFS, GFS, HDFS |
| I/O Model of Computation | p.1741 | Counting block transfers as the cost measure; buffering, prefetching runs, paginated indexes; binary tree vs B+-tree example |
| Information Lifecycle Management | p.1946 | Value-driven data placement across storage classes; HSM as the simple case |
| Intelligent Storage Systems | p.2009 | Database machines to storage-side functions (snapshots, replication, copy); OSD, SMI-S, XAM standards |
| IP Storage | p.2041 | iSCSI initiator/target, iFCP and FCIP for linking SAN islands |
| Logical Unit Number | p.2152 | LUN as the SCSI addressable unit; per-host numbering |
| Logical Unit Number Mapping | p.2153 | Host LUN assignment, LUN masking, interaction with multipathing and virtualization boxes |
| Logical Volume Manager | p.2153 | PV/PE/LE/VG/LV model, striped and mirrored logical volumes, online resize |
| Massive Array of Idle Disks | p.2211 | Spinning down cold drives in archival/nearline arrays by exploiting access locality |
| Memory Hierarchy | p.2222 | Cache capacity/line/associativity, miss taxonomy, sequential vs random latency/bandwidth, TLB, unified multi-level cost model |
| Multi-pathing | p.2419 | Active-active vs active-standby paths; avoiding double-visible volumes |
| Multitier Storage Systems | p.2446 | HSM history, three-tier enterprise storage, flash tiering with automated migration |
| Network Attached Secure Device | p.2489 | Object-based storage devices with a central policy server and direct client-device data path; ANSI T10 OSD |
| Network Attached Storage | p.2490 | File-level networked storage, NAS gateways/heads bridging SAN and NAS |
| Object Storage Protocol | p.2539 | RESTful GET/PUT immutable objects without POSIX; scale-out with erasure coding and eventually consistent metadata |
| Redundant Arrays of Independent Disks | p.3135 | Striping and parity; RAID levels 0-5 and how stripe-unit size separates them |
| SAN File System | p.3274 | Shared-disk file systems with cross-server cache coherency and direct SAN data path |
| SCSI Target | p.3326 | Targets exporting volumes mapped to host LUNs; what can act as a target |
| Software-Defined Storage | p.3545 | Control/data plane separation, policy-driven provisioning on commodity servers |
| Solid State Drive (SSD) | p.3545 | SSD as non-volatile memory behind block protocols; media variety (SLC/MLC/3D NAND, PCM, STT-MRAM), NVMe and KV interfaces |
| Storage Access Models | p.3722 | Tablespaces and containers; file-system-managed vs raw vs hybrid database-managed files; double buffering and direct I/O |
| Storage Area Network | p.3724 | Block-level storage networks; Fibre Channel SAN components; IP SAN |
| Storage Consolidation | p.3725 | Why storage is pooled on SAN/NAS: shared backup, DR, consistent policy |
| Storage Devices | p.3726 | Usability trade-offs of tape, disk, optical, flash, hybrid disks; erase-before-write and endurance of flash; WORM media |
| Storage Grid | p.3728 | Wide-area storage federations: organisation, bulk transport, replication strategy, scheduling |
| Storage Management | p.3730 | Device/configuration/performance/problem management, discovery and topology mapping, SMI-S |
| Storage Network Architectures | p.3741 | Server- vs storage-centric systems, FC protocol layers, iSCSI, NAS, LAN-free/server-free backup, sync vs async remote replication |
| Storage Power Management | p.3752 | Spindle power physics, break-even time, oracle vs threshold spin-down, DRPM, MAID caching and popular-data concentration |
| Storage Protection | p.3754 | Layered protection: drive ECC/CRC, replication, RAID, sync/async volume replication |
| Storage Protocols | p.3756 | FCP vs iSCSI, SCSI vs ATA command sets, parallel vs serial transports, NFS vs CIFS, NFSv4 delegations |
| Storage Resource Management | p.3759 | Capacity utilisation monitoring and forecasting across shared storage |
| Storage Virtualization | p.3762 | SNIA definition; block aggregation at host, network, or device layer; virtualization-based tiering |
| Write Once Read Many | p.4732 | Physical vs logical WORM for compliance archiving |

## Coverage notes

- **Solid State Drive (SSD)**: the cluster bundle cut this entry off after
  its header; the text was recovered from the book (printed p.3546). It is
  a short overview with no internals (no FTL, GC, or write amplification),
  so `ssd-and-flash-for-db-engines.md` is mostly marked Beyond EDBS.
- **Direct Attached Storage** is a two-sentence definition; recovered from
  the book likewise.
- Thin but used for vocabulary: Logical Unit Number, SCSI Target, Storage
  Resource Management, Storage Consolidation, Software-Defined Storage.
- The recovered tails of Storage Network Architectures and Logical Unit
  Number Mapping held no new mechanisms or readings; they contained the
  LVM entry's cross-references (Disk, RAID, Storage Management) and
  fragments of neighbouring entries. Two neighbours are worth knowing:
  Storage Networking Industry Association (p.3745; the standards body
  behind SMI-S, the shared storage model and the virtualization
  definitions used here) and Storage of Large Scale Multidimensional Data
  (p.3746, clustered under `olap-and-warehouse-engines`: tape-resident
  scientific arrays need a DBMS with an optimised tertiary-storage
  connection, e.g. the HEAVEN system).
- Storage Grid and Storage Management are oriented to administrators;
  only their engine-relevant points (bulk transfer, replica placement,
  topology/observability) are used.
