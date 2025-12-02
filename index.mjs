const BACKUP_BUCKET_NAME = "backup-uploads-tru-comp4980acc-karen";


import {Upload} from '@aws-sdk/lib-storage';
import { S3Client, GetObjectCommand, HeadObjectCommand } from "@aws-sdk/client-s3";
import { getSignedUrl } from "@aws-sdk/s3-request-presigner";

const s3client = new S3Client();

// event: notification from a S3 bucket, uploads-tru-comp4980acc, when a file is uploaded
export const handler = async (event, context) => {
    // the source bucket name
    const sourceBucket = event.Records[0].s3.bucket.name;
    // the path of the object (or file)
    const key = decodeURIComponent(event.Records[0].s3.object.key.replace(/\+/g, ' '));

    // Just in case,
    if (BACKUP_BUCKET_NAME == sourceBucket) {
        console.log("Warning: the source bucket is the same as the backup bucket.");
        return;
    }

    // Read a file from sourceBucket and upload it to the backup bucket
    const response = await readFileFromS3Bucket(sourceBucket, key);

    if (response.result)
        await uploadFileToS3Bucket(BACKUP_BUCKET_NAME, key, response.body);
    else
        console.log("File reading unsuccessful!");
};

async function readFileFromS3Bucket(sourceBucket, key) {
  try {
      // get the object (or file) from the source s3 bucket
      const params = {
          Bucket: sourceBucket,  // the bucket name
          Key: key              // the path of object (or file)
      };
      const command = new GetObjectCommand(params);
      const response = await s3client.send(command);


      return { result: true, body: response.Body };
  } catch (err) {
      console.error("Error reading from S3:", err);
      return { result: false, body: null };
  }
}


async function uploadFileToS3Bucket(BACKUP_BUCKET_NAME, key, body)
{
    // Check if the object/file exists
try {
  const { ContentType } = await s3client.send(new HeadObjectCommand({
      Bucket: BACKUP_BUCKET_NAME, Key: key }));
  //console.log("The file already exists.");
}
// If the object/file does not exist, then upload it.
catch(err) {
  const params = {
      Bucket: BACKUP_BUCKET_NAME,  // the bucket name
      Key: key,  // the path of object (or file)
      Body: body  // the object (or file) content
  };
  /* It does not work. Wondering why? Maybe missed ContentType in params?
  const command = new PutObjectCommand(params);
  const response = await s3client.send(command);
  */
  const uploads3 = new Upload({
      client: s3client,
      params: params
  });
  const response = await uploads3.done();
}
}


