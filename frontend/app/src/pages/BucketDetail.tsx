import { BucketDetailPanel } from "../shared";

/** One time bucket's session breakdown. Its own page: `/cost/time/:grain/:bucket`,
 *  promoted out of Time's own table so a list page never stacks a second one inline. */
export function BucketDetail({ grain, bucket }: { grain: string; bucket: string }) {
  return <BucketDetailPanel grain={grain} bucket={bucket} hint="" />;
}
